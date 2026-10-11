"""Builder: reads a bank's brief and its tool API file, creates the phone agent on Freya.

    python builder/build.py BRIEF.md [MORE_BRIEFS.md ...] TOOL_API.json
    python builder/build.py CASE_FOLDER_OR_ZIP MOCK_URL        (final format: a folder of bank documents)

Examples:
    python builder/build.py briefs/brief-a.md tools/openapi.json
    python builder/build.py briefs/brief-a.md briefs/brief-b.md tools/openapi.json
    python builder/build.py briefs/hidden-1.md briefs/hidden-1.openapi.json

Claude (through the Claude Agent SDK) follows the skill .claude/skills/build-phone-agent: it reads
the brief, writes and checks the workflow, saves it to Freya, tests it where practice customers
exist, and fixes what fails. This file only starts it, enforces the time limit, exports the result
and writes the trace. It holds no bank rule.

Needs FREYA_API_KEY and FREYA_BANK_TEAM_KEY, and a Claude login or ANTHROPIC_API_KEY.
Writes:
    traces/<slot>-<time>.log     the readable trace to submit (start, end, model calls, what was created, tests)
    traces/<slot>-<time>.jsonl   every message of the run
    submission/<slot>.workflow.json   the exported phone agent
"""
import asyncio, dataclasses, json, os, pathlib, sys, time

import re
from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, HookMatcher, ResultMessage, TextBlock, ToolResultBlock, ToolUseBlock, UserMessage, query

KIT = pathlib.Path(__file__).resolve().parent.parent

# Windows consoles (and output piped through Tee-Object) often use a legacy code page that cannot
# print characters such as an arrow. Never let printing a trace line crash the builder.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
sys.path.insert(0, str(KIT))
MODEL = os.environ.get("BUILDER_MODEL", "claude-opus-5-5")
LIMIT_S = int(os.environ.get("BUILDER_LIMIT_S", str(28 * 60)))     # the event allows 30 minutes per brief


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


class Trace:
    def __init__(self, slot):
        stamp = time.strftime("%Y%m%d-%H%M%S")
        (KIT / "traces").mkdir(exist_ok=True)
        self.log = open(KIT / "traces" / f"{slot}-{stamp}.log", "w", encoding="utf-8")
        self.raw = open(KIT / "traces" / f"{slot}-{stamp}.jsonl", "w", encoding="utf-8")
        self.calls = 0
        self.tests = []     # one entry per practice run: passed, total, and the workflow file that was tested

    def line(self, text):
        try:
            print(text, flush=True)
        except Exception:
            try:
                print(text.encode("ascii", "replace").decode("ascii"), flush=True)
            except Exception:
                pass
        self.log.write(text + "\n"); self.log.flush()

    def message(self, m):
        self.raw.write(json.dumps({"at": now(), "type": type(m).__name__, **dataclasses.asdict(m)}, default=str) + "\n"); self.raw.flush()


# Platform credit guard. The model can ignore a rule in the skill; this cannot be ignored.
MAX_CHAT_TURNS = int(os.environ.get("BUILDER_MAX_CHAT", "3"))
MAX_TEST_RUNS = int(os.environ.get("BUILDER_MAX_TESTS", "2"))


def practice_brief_letter(slot):
    """'brief-a' -> 'A' when the kit has practice customers for Brief A, else None."""
    try:
        letters = {c["brief"] for c in json.loads((KIT / "public-test-set.json").read_text(encoding="utf-8"))}
    except Exception:
        letters = set()
    letter = slot.split("-")[-1].upper()
    return letter if letter in letters else None


MAX_CASE_SIMS = int(os.environ.get("BUILDER_MAX_CASE_SIMS", "2"))


def make_guard(slot, trace, case=False):
    used = {"chat": 0, "tests": 0, "case_sims": 0}
    trace.guard_used = used
    allowed_letter = practice_brief_letter(slot)

    def command_text(cmd):
        text = cmd
        rest = re.sub(r'^\s*(cd\s+("[^"]*"|\S+)\s*(;|&&)\s*)*', "", cmd)
        first = rest.split()
        if first and first[0] in ("grep", "sed", "cat", "head", "tail", "wc", "ls") and not re.search(r"[;&]|\|\s*(python|py|\S*python\S*)\b", rest):
            return text                                  # reading a file is not running it
        for path in re.findall(r"[\w./\\-]+\.py", cmd):     # also look inside scripts the command runs
            f = (KIT / path) if not os.path.isabs(path) else pathlib.Path(path)
            try:
                if f.is_file() and f.stat().st_size < 400_000: text += "\n" + f.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                pass
        return text

    def deny(reason):
        trace.line("    GUARD blocked a command: " + reason)
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": reason}}

    async def guard(hook_input, tool_use_id, context):
        cmd = str((hook_input.get("tool_input") or {}).get("command", ""))
        if case and "sim_check.py" in cmd:
            # a case folder: its test customers live on the team's mock, so a few hand-written customers can test the agent
            if used["case_sims"] >= MAX_CASE_SIMS:
                return deny(f"the limit of {MAX_CASE_SIMS} simulation checks per build is reached. Finish with what you have.")
            used["case_sims"] += 1
            return {}
        text = command_text(cmd)
        if "run_cases" in text or "/api/v2/simulations" in text or "run_simulation" in text:
            if not allowed_letter:
                return deny(f"no practice customers exist for {slot}; simulations would test other rules and spend credit. Rely on the local checks and the lint.")
            if re.search(r"--brief\s+([A-Za-z])", cmd) and re.search(r"--brief\s+([A-Za-z])", cmd).group(1).upper() != allowed_letter:
                return deny(f"this build is for Brief {allowed_letter}; run the practice customers with --brief {allowed_letter} only.")
            if used["tests"] >= MAX_TEST_RUNS:
                return deny(f"the limit of {MAX_TEST_RUNS} practice runs per build is reached. Finish with what you have.")
            used["tests"] += 1
        if "chat/message" in text:
            if used["chat"] >= MAX_CHAT_TURNS:
                return deny(f"the limit of {MAX_CHAT_TURNS} chat checks per build is reached. Chat costs platform credit and cannot test bank tools. Use the local checks.")
            used["chat"] += 1
        return {}

    return guard


def one_line(text, n=140):
    return " ".join(str(text).split())[:n]


def case_prompt(case, slot, py):
    return (
        "Use the build-phone-agent skill to build a phone agent.\n"
        f"Case: {case['source']}. It is a folder of the bank's documents (brief, readme, analysis, flow drawing, "
        "announcements, service contract, test customers, Q&A, example conversations). Every document, converted to "
        f"text, is listed in {case['index']}: read that index first, then every file it lists. Open PDFs and images "
        "it marks with the Read tool. Follow the skill's section 'Case folders'.\n"
        f"Bank API: the team's mock bank serves the service contract at {case['mock_url']}: take the contract's base address, "
        f"replace its scheme and host with {case['mock_url']} and keep its path (so every tool URL is {case['mock_url']}/<contract path>). "
        "The mock answers exactly as the case's test environment says, for its test customers.\n"
        f"Before step 4, write the tool API file out/{slot}.openapi.json (OpenAPI 3) from the service contract, with "
        f"servers[0].url = {case['mock_url']}; it is the tool API file for the rest of the skill (lint included).\n"
        f"Slot: {slot} (use it for out/ file names and for freya.save_workflow).\n"
        f"You have {LIMIT_S // 60} minutes in total from now, tests included. Run `date` to keep track.\n"
        f"Python: run every Python command with \"{py}\" (quoted). It is the interpreter this builder runs on, with working network certificates. Do not use another python.\n"
        f"Write only files named {slot}* in out/. Do not open, read or copy any other file in out/ or out/_other/: those belong to other briefs and their rules do not apply here.\n"
        "Never write a rule, value or name into any file outside out/ and the workflow you save."
    )


async def build(briefs, tool_api, slot, trace, case=None):
    py = sys.executable.replace("\\", "/")
    prompt = case_prompt(case, slot, py) if case else (
        "Use the build-phone-agent skill to build a phone agent.\n"
        f"Brief files: {' '.join(briefs)}\n"
        f"Tool API file: {tool_api}\n"
        f"Slot: {slot} (use it for out/ file names and for freya.save_workflow).\n"
        f"You have {LIMIT_S // 60} minutes in total from now, tests included. Run `date` to keep track.\n"
        f"Python: run every Python command with \"{py}\" (quoted). It is the interpreter this builder runs on, with working network certificates. Do not use another python.\n"
        f"Write only files named {slot}* in out/. Do not open, read or copy any other file in out/ or out/_other/: those belong to other briefs and their rules do not apply here.\n"
        "Never write a rule, value or name into any file outside out/ and the workflow you save."
    )
    options = ClaudeAgentOptions(
        cwd=KIT,
        model=MODEL,
        skills=["build-phone-agent"],
        setting_sources=["project"],
        allowed_tools=["Read", "Write", "Edit", "Glob", "Grep", "Bash"],
        permission_mode="dontAsk",
        max_turns=200,
        hooks={"PreToolUse": [HookMatcher(matcher="Bash", hooks=[make_guard(slot, trace, bool(case))])]},
        env={"PYTHON": py, "BASH_DEFAULT_TIMEOUT_MS": "900000", "BASH_MAX_TIMEOUT_MS": "1200000", "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS": "1"},
    )
    # The SDK's cleanup after a stop (time limit, error) reports through the loop's exception
    # handler; send that to the trace instead of a red traceback on the console.
    asyncio.get_running_loop().set_exception_handler(
        lambda loop, ctx: trace.line("    (async cleanup: " + one_line(ctx.get("message", ""), 120) + ")"))
    pending = {}
    stream = query(prompt=prompt, options=options)
    try:
        # The time limit runs in this task, so the SDK stream is stopped and closed in the task
        # that opened it (asyncio.wait_for would close it from another task and crash the cleanup).
        async with asyncio.timeout(LIMIT_S):
            await consume(stream, trace, slot, pending)
    finally:
        try:
            await stream.aclose()
        except (Exception, asyncio.CancelledError):
            pass


async def consume(stream, trace, slot, pending):
    async for m in stream:
        trace.message(m)
        if isinstance(m, AssistantMessage):
            trace.calls += 1
            what = []
            for b in m.content:
                if isinstance(b, TextBlock) and b.text.strip():
                    what.append("says: " + one_line(b.text, 100))
                elif isinstance(b, ToolUseBlock):
                    arg = b.input.get("command") or b.input.get("file_path") or b.input.get("pattern") or ""
                    what.append(f"{b.name} {one_line(arg, 110)}")
                    pending[b.id] = (b.name, str(arg))
            trace.line(f"[{time.strftime('%H:%M:%S')}] model call {trace.calls} ({MODEL}): " + (" | ".join(what) or "(no text)"))
        elif isinstance(m, UserMessage) and isinstance(m.content, list):
            for b in m.content:
                if isinstance(b, ToolResultBlock) and b.tool_use_id in pending:
                    name, arg = pending.pop(b.tool_use_id)
                    out = b.content if isinstance(b.content, str) else json.dumps(b.content, default=str)
                    if "run_cases.py" in arg:
                        trace.line("    TEST " + arg)
                        for l in str(out).splitlines():
                            if l.startswith(("PASS", "FAIL")) or "passed" in l or l.strip().startswith("- "): trace.line("      " + l[:260])
                        score = re.search(r"(\d+) / (\d+) passed", str(out))
                        if not score and getattr(trace, "guard_used", None) and trace.guard_used["tests"] > 0:
                            trace.guard_used["tests"] -= 1      # a platform error (504, crash) gave no result: not counted
                            trace.line("      no result (platform error): this run is not counted against the limit")
                        wf_file = KIT / "out" / f"{slot}.workflow.json"
                        if score and wf_file.exists():
                            trace.tests.append({"passed": int(score.group(1)), "total": int(score.group(2)), "workflow": wf_file.read_text(encoding="utf-8")})
                    elif "sim_check.py" in arg:
                        trace.line("    SIM CHECK " + one_line(arg, 120))
                        for l in str(out).splitlines():
                            if ": PASS" in l or ": FAIL" in l or l.startswith("simulation "): trace.line("      " + l[:220])
                    elif "lint_workflow.py" in arg:
                        last = [l for l in str(out).splitlines() if l.strip()]
                        trace.line("    LINT " + (last[-1][:160] if last else "(no output)"))
                    elif "save_workflow" in arg or "validate_workflow" in arg:
                        trace.line("    FREYA " + one_line(out, 200))
        elif isinstance(m, ResultMessage):
            trace.line(f"builder agent finished: {m.num_turns} turns, {m.duration_ms / 1000:.0f} s, ${m.total_cost_usd or 0:.2f}")


def main():
    args = sys.argv[1:]
    case = None
    if len(args) == 2 and re.match(r"https?://", args[1]):
        src = pathlib.Path(args[0]) if pathlib.Path(args[0]).exists() else KIT / args[0]
        if not src.exists():
            sys.exit(f"not found: {args[0]}")
        src = src.resolve()
        slot = re.sub(r"[^a-z0-9]+", "-", src.stem.lower()).strip("-") or "case"
        case = {"source": str(src), "mock_url": args[1].rstrip("/")}
        briefs, tool_api = [str(src)], f"out/{slot}.openapi.json"
    else:
        if len(args) < 2 or not args[-1].endswith(".json"):
            sys.exit(__doc__)
        briefs, tool_api = args[:-1], args[-1]
        for p in briefs + [tool_api]:
            if not (KIT / p).exists() and not pathlib.Path(p).exists():
                sys.exit(f"not found: {p}")
        slot = pathlib.Path(briefs[-1]).stem
    os.chdir(KIT)        # freya.save_workflow keeps its slot file in the working directory
    # Files that earlier runs left in out/ for other briefs are moved aside, so this run starts clean
    # and cannot copy another brief's rules by accident.
    out = KIT / "out"; out.mkdir(exist_ok=True)
    other = out / "_other"
    for f in list(out.iterdir()):
        if f.name != "_other" and not f.name.startswith(slot):
            other.mkdir(exist_ok=True)
            target = other / f.name
            if target.exists():
                target = other / (f.stem + time.strftime("-%H%M%S") + f.suffix)
            f.rename(target)
    trace = Trace(slot)
    t0 = time.time()
    if case:
        sys.path.insert(0, str(KIT / "builder"))
        import materials
        index, rows = materials.convert(case["source"], out / f"{slot}_materials")
        case["index"] = str(index.relative_to(KIT)).replace("\\", "/")
        trace.line(f"case {case['source']}: {len(rows)} files, text in {case['index']}; mock bank {case['mock_url']}")
        for a, b, c, d in rows:
            trace.line(f"    {a}: {c or d}")
    trace.line(f"start {now()}")
    trace.line(f"briefs {briefs}, tool API {tool_api}, slot {slot}, builder model {MODEL}, limit {LIMIT_S} s")
    try:
        asyncio.run(build(briefs, tool_api, slot, trace, case))
    except (asyncio.TimeoutError, TimeoutError):
        trace.line(f"time limit of {LIMIT_S} s reached: stopping the builder agent. The last saved workflow stands.")
    except Exception as e:
        trace.line(f"builder agent stopped with an error: {e!r}. The last saved workflow, if any, stands.")

    import freya
    # Keep the best tested version. A fix made after a test can make the agent worse, and an
    # untested change is a guess: the version that scored best on the practice customers stands.
    if trace.tests:
        best = max(enumerate(trace.tests), key=lambda it: (it[1]["passed"], it[0]))[1]
        wf_file = KIT / "out" / f"{slot}.workflow.json"
        current = wf_file.read_text(encoding="utf-8") if wf_file.exists() else ""
        if current != best["workflow"]:
            try:
                r = freya.save_workflow(slot, json.loads(best["workflow"]))
                (KIT / "out" / f"{slot}.final.workflow.json").write_text(best["workflow"], encoding="utf-8")
                trace.line(f"kept the best tested version ({best['passed']}/{best['total']} passed): saved it again as version {r.get('version')}; the later, untested or worse version is not submitted")
            except Exception as e:
                trace.line(f"could not restore the best tested version: {e!r}")
        else:
            trace.line(f"the saved version is the best tested one ({best['passed']}/{best['total']} passed)")
    state = KIT / ".freya-agents.json"
    saved = json.loads(state.read_text()).get(slot) if state.exists() else None
    if saved:
        (KIT / "submission").mkdir(exist_ok=True)
        path = KIT / "submission" / f"{slot}.workflow.json"
        try:
            freya.export_workflow(saved["workflow_id"], str(path))
            wf = json.loads(path.read_text(encoding="utf-8"))["workflow"]
            nodes = wf.get("nodes", {})
            tools = {t["function"]["name"] for n in nodes.values() for t in (n.get("tools") or []) + (n.get("pre_actions") or [])}
            trace.line(f"created on Freya: workflow_id {saved['workflow_id']}, agent_id {saved['agent_id']}, version {saved.get('version', 1)}, {len(nodes)} steps, {len(tools)} tools ({', '.join(sorted(tools))})")
            trace.line(f"exported to {path.relative_to(KIT)}")
        except Exception as e:
            trace.line(f"export failed: {e!r}. workflow_id {saved['workflow_id']}, agent_id {saved['agent_id']}")
    else:
        trace.line("nothing was saved on Freya for this slot")
    trace.line(f"end {now()}, build time {time.time() - t0:.0f} s, {trace.calls} model calls")


if __name__ == "__main__":
    main()
