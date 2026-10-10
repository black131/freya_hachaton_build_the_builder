"""Check a Freya workflow JSON for the mistakes the platform accepts without an error.

    python lint_workflow.py out/brief-a.workflow.json --openapi tools/openapi.json [--vars customer_id,first_name,last_name,title,now]

Exit code 1 when there is an ERROR. WARN lines are worth reading too. Run it before every save:
a save costs nothing, but a simulation of a broken workflow costs a test run and minutes.
"""
import argparse, json, re, sys

ERR, WARN = [], []
CONV_ONLY = {"conversation"}
ACTION_TYPES = {"api_request", "code"}
WRITE_TOOLS = {"create_promise", "add_note", "schedule_callback", "transfer_to_agent", "close_call"}
PH = re.compile(r"\{\{\s*([^}:\s]+)")


def err(msg): ERR.append(msg)
def warn(msg): WARN.append(msg)


def walk_nulls(x, path="workflow"):
    if x is None:
        warn("%s is null. The docs say the schema rejects null: leave the field out or use \"\"." % path)
    elif isinstance(x, dict):
        for k, v in x.items(): walk_nulls(v, path + "." + str(k))
    elif isinstance(x, list):
        for i, v in enumerate(x): walk_nulls(v, "%s[%d]" % (path, i))


def check_condition(c, where, written):
    if not isinstance(c, dict):
        err("%s: condition is not an object" % where); return
    if c.get("logic") == "and" and where.endswith("condition"):
        err("%s: top-level logic 'and'. Put the AND group inside a top-level OR group." % where)
    conds = c.get("conditions")
    if isinstance(conds, list):
        trues = [x for x in conds if isinstance(x, dict) and str(x.get("operand")) in ("true", "True") and x.get("operator") == "equals"]
        for v in {x.get("variable") for x in trues}:
            spellings = {str(x.get("operand")) for x in trues if x.get("variable") == v}
            if len(spellings) == 1:
                warn("%s: boolean test on %s with only %r. Test both 'true' and 'True'." % (where, v, spellings.pop()))
        for x in conds: check_condition(x, where + ".group", written)
    op = c.get("operator")
    if op and op not in ("equals", "not_equals", "greater_than", "less_than", "contains", "is_set", "is_not_set", "always", "matches_intent"):
        err("%s: unknown operator %r" % (where, op))
    if op == "matches_intent" and not c.get("description"):
        err("%s: matches_intent without a description" % where)


def check_tool(t, where, openapi, node_type, bank_used):
    f = t.get("function", {})
    name, handler = f.get("name", "?"), f.get("handler", "")
    w = "%s tool %s" % (where, name)
    props = f.get("parameters", {}).get("properties", {})
    if "const" in json.dumps(f.get("parameters", {})):
        err("%s: uses 'const'. Only 'default' sends a value." % w)
    if handler == "__function__:api_call":
        url = props.get("url", {}).get("default")
        if not url: err("%s: url has no default" % w)
        if "method" not in props or "default" not in props.get("method", {}): err("%s: method has no default" % w)
        body = props.get("body", {})
        if "default" in body and isinstance(body.get("default"), dict):
            err("%s: body is a single default object. Declare each field under body.properties with its own default." % w)
        fields = body.get("properties", {})
        for fn, spec in fields.items():
            if "default" not in spec:
                warn("%s: body field %s has no default. Use \"{{%s}}\" so the model fills it, or a fixed value." % (w, fn, fn))
        if openapi is not None and url:
            op = openapi.get(url.rsplit("/", 1)[-1]) if isinstance(url, str) else None
            if op is None and isinstance(url, str) and url.startswith(openapi.get("__server__", "~")):
                err("%s: url %s is not a path in the tool API file" % (w, url))
            if op is not None:
                bank_used.add(url.rsplit("/", 1)[-1])
                if not url.startswith(openapi["__server__"]):
                    err("%s: url does not start with the server %s" % (w, openapi["__server__"]))
                api_props = op.get("properties", {})
                for fn in fields:
                    if fn not in api_props: err("%s: body field %s is not in the tool API" % (w, fn))
                for fn in op.get("required", []):
                    if fn not in fields: err("%s: required API field %s is missing from the body" % (w, fn))
                for fn, aspec in api_props.items():
                    if "enum" in aspec and fn in fields:
                        mine = fields[fn].get("enum")
                        d = str(fields[fn].get("default", ""))
                        if mine and set(mine) - set(aspec["enum"]):
                            err("%s: enum of %s has values the API does not allow: %s" % (w, fn, sorted(set(mine) - set(aspec["enum"]))))
                        if not mine and d.startswith("{{"):
                            warn("%s: model-filled field %s has no enum. The API allows only %s." % (w, fn, aspec["enum"]))
                if "customer_id" in api_props and fields.get("customer_id", {}).get("default") != "{{customer_id}}":
                    err("%s: customer_id must have default \"{{customer_id}}\" (baked from the call variable)" % w)
        retries = t.get("config", {}).get("maxRetries", 0)
        if name in WRITE_TOOLS and retries:
            err("%s: maxRetries %s on a tool that writes. A retried write can record twice. Use 0." % (w, retries))
    if handler == "__function__:code_exec":
        code = props.get("code", {}).get("default", "")
        if "{" * 2 in code or "}" * 2 in code: err("%s: code contains a doubled brace" % w)
        try: compile(code, name, "exec")
        except SyntaxError as e: err("%s: code does not compile: %s line %s" % (w, e.msg, e.lineno))
        if "try:" not in code: warn("%s: code has no try/except. An exception leaves its variables unset." % w)
    for m in t.get("response_mapping", []) or []:
        if not str(m.get("path", "")).startswith("data."): warn("%s: mapping path %s does not start with data." % (w, m.get("path")))
    for hook in ("pre_process_code", "post_process_code"):
        code = t.get(hook)
        if code:
            if handler != "__function__:api_call": err("%s: %s on a non api_call tool is removed by the platform" % (w, hook))
            try: compile(code, hook, "exec")
            except SyntaxError as e: err("%s: %s does not compile: %s line %s" % (w, hook, e.msg, e.lineno))
            if "try:" not in code: warn("%s: %s has no try/except" % (w, hook))
    if node_type == "conversation" and handler == "__function__:api_call" and name in WRITE_TOOLS and "CALL" not in f.get("description", "").upper():
        warn("%s: the description does not say when to call it. The model may only talk about it." % w)


def written_variables(wf, call_vars):
    out = set(call_vars) | set(wf.get("test_variables", {}))
    allnodes = dict(wf.get("nodes", {})); allnodes.update(wf.get("global_nodes", {}) or {})
    for key, n in allnodes.items():
        for e in n.get("extraction_schema", []) or []: out.add(e.get("name"))
        for m in n.get("response_mapping", []) or []: out.add(m.get("variable"))
        out.add(key + "_response"); out.add(key + "_success_count"); out.add(key + "_failure_count")
        for t in (n.get("tools", []) or []) + (n.get("pre_actions", []) or []):
            nm = t.get("function", {}).get("name", "")
            out.update({nm + "_response", nm + "_args", nm + "_success_count", nm + "_failure_count", nm + "_status_code"})
            for m in t.get("response_mapping", []) or []: out.add(m.get("variable"))
            code = t.get("function", {}).get("parameters", {}).get("properties", {}).get("code", {}).get("default", "")
            out.update(re.findall(r"vars\[['\"](\w+)['\"]\]\s*=", code))
            for hook in ("pre_process_code", "post_process_code"):
                out.update(re.findall(r"vars\[['\"](\w+)['\"]\]\s*=", t.get(hook) or ""))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workflow")
    ap.add_argument("--openapi")
    ap.add_argument("--vars", default="customer_id,first_name,last_name,title,now", help="call variables, comma separated")
    a = ap.parse_args()
    wf = json.load(open(a.workflow, encoding="utf-8"))
    if "workflow" in wf and "nodes" not in wf: wf = wf["workflow"]
    openapi = None
    if a.openapi:
        spec = json.load(open(a.openapi, encoding="utf-8"))
        openapi = {"__server__": spec["servers"][0]["url"].rstrip("/") + "/"}
        for p, ops in spec["paths"].items():
            for meth, d in ops.items():
                openapi[p.strip("/")] = d.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema", {})
    call_vars = [v.strip() for v in a.vars.split(",") if v.strip()]

    walk_nulls(wf)
    if "agent_config" in wf: err("agent_config is present. Leave it out.")
    nodes, globs = wf.get("nodes", {}), wf.get("global_nodes", {}) or {}
    if wf.get("initial_node") not in nodes: err("initial_node %r is not a node" % wf.get("initial_node"))
    written = written_variables(wf, call_vars)
    bank_used = set()
    ends = {k for k, n in nodes.items() if n.get("node_type") == "end_call"}
    has_end_tool = any(t.get("function", {}).get("handler") == "__function__:end_call" for n in nodes.values() for t in n.get("tools", []) or [])
    if not ends and not has_end_tool: err("no end_call node and no end_call tool: no call can end")

    for key, n in list(nodes.items()) + [("global:" + k, v) for k, v in globs.items()]:
        nt, w = n.get("node_type"), "node " + key
        bare = key.split(":", 1)[-1]
        if n.get("name") != bare: warn("%s: name %r differs from its key" % (w, n.get("name")))
        if nt not in ("conversation", "api_request", "code", "end_call"): warn("%s: node_type %r is not one of the four this event needs" % (w, nt))
        if n.get("tools") and nt not in CONV_ONLY: err("%s: tools on a %s node are removed by the platform" % (w, nt))
        if n.get("pre_actions") and nt not in ACTION_TYPES: err("%s: pre_actions on a %s node are removed by the platform" % (w, nt))
        for pa in n.get("pre_actions", []) or []:
            if pa.get("response_mapping"): err("%s: response_mapping inside a pre_action is ignored. Put it on the node." % w)
        for t in (n.get("tools", []) or []) + (n.get("pre_actions", []) or []):
            check_tool(t, w, openapi, nt, bank_used)
        trs = n.get("transitions", []) or []
        for i, tr in enumerate(trs):
            tgt = tr.get("target_node")
            if tgt not in nodes and not (tgt == "__previous__" and key.startswith("global:")): err("%s: transition %d targets unknown node %r" % (w, i, tgt))
            if "condition" in tr: check_condition(tr["condition"], "%s transition %d condition" % (w, i), written)
            else: err("%s: transition %d has no condition" % (w, i))
            for v in re.findall(r'"variable":\s*"([^"]+)"', json.dumps(tr)):
                root = v.split(".")[0]
                if v not in written and root not in written and not any(v.startswith(x + ".") for x in written):
                    warn("%s: transition %d tests %r, which nothing in the workflow writes" % (w, i, v))
        if n.get("passthrough"):
            if not trs or trs[-1].get("condition", {}).get("operator") != "always": err("%s: passthrough node must end with an 'always' transition (else it deadlocks)" % w)
            if not n.get("passthrough_default_transition"): err("%s: passthrough node without passthrough_default_transition" % w)
        if nt == "end_call":
            if trs: err("%s: end_call node has transitions" % w)
            if not n.get("terminal"): err("%s: end_call node has no terminal" % w)
        if nt == "conversation":
            if not trs and not any(t.get("function", {}).get("handler") == "__function__:end_call" for t in n.get("tools", []) or []):
                warn("%s: conversation node with no transitions and no end_call tool: the call can never leave it" % w)
            if n.get("max_node_turns") and not n.get("max_turn_transition"): warn("%s: max_node_turns without max_turn_transition does nothing" % w)
        for e in n.get("extraction_schema", []) or []:
            if "min_confidence" not in e: warn("%s: extraction %s has no min_confidence (default 0.95 discards most values)" % (w, e.get("name")))
            if e.get("extraction_prompt") and "{{extractor.speech}}" not in e["extraction_prompt"]: err("%s: extraction_prompt lacks the extractor placeholders" % w)
        text = " ".join(str(n.get(f, "")) for f in ("task_message", "loop_prompt", "role_message")) + " " + json.dumps(n.get("on_enter", {}))
        for v in set(PH.findall(text)):
            root = v.split(".")[0]
            if v not in written and root not in written and not root.startswith(("system", "call")) and not any(v.startswith(x + ".") for x in written):
                warn("%s: prompt uses {{%s}}, which nothing writes. The model will see the raw placeholder." % (w, v))
    text = wf.get("system_prompt", "")
    for v in set(PH.findall(text)):
        if v not in written and not v.startswith(("system", "call")): warn("system_prompt uses {{%s}}, which nothing writes" % v)

    # every node must be able to reach an end_call node
    graph = {k: {tr.get("target_node") for tr in n.get("transitions", []) or []} | ({n["max_turn_transition"]} if n.get("max_turn_transition") else set()) for k, n in nodes.items()}
    can_end = set(ends)
    changed = True
    while changed:
        changed = False
        for k, outs in graph.items():
            if k not in can_end and (outs & can_end or any(t.get("function", {}).get("handler") == "__function__:end_call" for t in nodes[k].get("tools", []) or [])):
                can_end.add(k); changed = True
    for k in nodes:
        if k not in can_end: err("node %s cannot reach an end_call node" % k)
    seen, todo = set(), [wf.get("initial_node")]
    while todo:
        k = todo.pop()
        if k in seen or k not in graph: continue
        seen.add(k); todo.extend(graph[k])
    for k in nodes:
        if k not in seen: warn("node %s is never reached from initial_node" % k)

    # a model-filled field "{{x}}" is baked instead when a variable x exists: warn on clashes
    model_filled = set()
    for n in list(nodes.values()) + list(globs.values()):
        for t in n.get("tools", []) or []:
            body = t.get("function", {}).get("parameters", {}).get("properties", {}).get("body", {}).get("properties", {})
            for fn, spec in body.items():
                d = str(spec.get("default", ""))
                m = re.fullmatch(r"\{\{\s*(\w+)\s*\}\}", d)
                if m and m.group(1) != "customer_id": model_filled.add(m.group(1))
    produced = written_variables(wf, []) - set(call_vars)
    for v in sorted(model_filled & (produced | set(call_vars) | set(wf.get("test_variables", {})))):
        warn("model-filled field {{%s}} has the same name as a variable the workflow sets. Once that variable is set the field is baked and the model cannot fill it. Fine if you set it on purpose to bake the value; otherwise rename the variable." % v)

    if openapi is not None:
        api_tools = {k for k in openapi if k != "__server__"}
        for t in wf.get("tools", []) or []:
            u = t.get("function", {}).get("parameters", {}).get("properties", {}).get("url", {}).get("default", "")
            if isinstance(u, str): bank_used.add(u.rsplit("/", 1)[-1])
        unused = sorted(api_tools - bank_used)
        if unused: warn("bank tools never offered to the agent: %s. Fine only if the brief never needs them." % ", ".join(unused))

    for m in ERR: print("ERROR", m)
    for m in WARN: print("WARN ", m)
    print("%d errors, %d warnings, %d nodes" % (len(ERR), len(WARN), len(nodes)))
    sys.exit(1 if ERR else 0)


if __name__ == "__main__":
    main()
