---
name: build-phone-agent
description: Build a Freya phone agent (a workflow JSON) from a bank's collection-call brief and its tool API file, check it, save it and test it on the practice customers where they exist. Use whenever you are asked to build, rebuild or improve a phone agent from a brief, including a brief you have never seen or one delivered as raw bank documents (mails, policy extracts, memos, code lists).
---

# Build a phone agent from a brief

You turn a bank's brief into a Freya workflow that phones a late customer. Simulated customers
talk to it three times each, and a customer counts only when the bank's records and the
conversation are right in all three runs. Nobody edits your workflow afterwards, so everything
the agent needs must be in what you build.

Work from the kit folder. Everything you build comes from the brief files and the tool API file
you were given. Do not open files that earlier runs left in `out/` for other briefs: start every
build from this skill, not from another brief's build script. Never carry a rule, value, sentence or name over from another brief, an example or
this skill.

## Time

You have 30 minutes for the whole run, tests included. Run `date` at the start and before every
long step. A plan that fits:

| Minutes | Step |
|---|---|
| 0 to 8 | read, write the spec |
| 8 to 18 | write the build script, test the code nodes locally, lint, save |
| 18 to 28 | one practice run if practice customers exist for this brief, one round of fixes |
| last 2 | save, export, final line |

If you are behind, skip the second practice run, never the lint.

The commands below run from the kit folder and say `python`. When the environment variable
`PYTHON` is set (the builder sets it), use `"$PYTHON"` in its place: another python on the machine
may lack network certificates. Otherwise, on Windows, the interpreter is often `py`. `$SKILL` below means
`.claude/skills/build-phone-agent`.

If `FREYA_API_KEY` is not set, you cannot reach the platform: do steps 1 to 5, then stop and say so.

## Steps

1. **Read.** The brief files, then the tool API file. Then `docs/workflow-format.md` and
   `docs/tools-and-code.md` (the "Checklist" at the end of the second one is the short form).
   Then `references/architecture.md` in this skill: it is the workflow shape to start from, with
   recipes for every part.

2. **Write the spec** `out/<slot>.spec.md`, following `references/reading-a-brief.md`. `<slot>`
   is the last brief file's name without `.md`. Every rule of the brief gets one line and a place
   in the workflow. If the brief is raw bank material, resolve which document wins for each rule
   first. Count the brief's numbered rules and check your list has them all.

3. **Write the code-node snippets** in `out/`: one for the calendar facts (from `now`), one for
   the account facts (from the product list). Use the helpers in `scripts/calendar_lib.py`
   (Calendar, parse_now, spoken, read_list, money); the values go in a `RULES` dict copied from
   the spec. Test each one before it goes anywhere:

   ```bash
   python $SKILL/scripts/build_code.py out/setup_snippet.py --run out/vars_example.json --expect date_facts
   python $SKILL/scripts/build_code.py out/account_snippet.py --run out/vars_example.json --expect account_facts
   ```

   Build the example `vars` from a practice case of this brief (`public-test-set.json` has `now`
   and the products of each), or from the dates and figures the brief itself uses as examples.
   Also run each snippet on empty `vars` to see its fallback. Read the printed facts and check
   each date against the brief by hand, once. The account snippet can also build the fixed
   sentence that states the debt (see `references/architecture.md`, 3.6).

4. **Write a build script** `out/<slot>_build.py` that assembles the workflow from the spec and
   the snippets and writes `out/<slot>.workflow.json` with `json.dump`. Never write the workflow
   JSON by hand: code and hooks need escaping. Start from the graph in `references/architecture.md`:
   - a code node first, computing date facts;
   - a greeting with the brief's fixed opening line, forking on an extracted enum;
   - identity checking with a post-hook on the verify tool that says what to do next;
   - the account fetched in a `pre_actions` node, never left to the model;
   - account facts computed in code;
   - one negotiation node with the decision table from the spec and no recording tools, and a
     recording node entered on an extracted confirmation, with an `llm` entry that calls the tool at
     once, never a silent entry (3.8, 3.9);
   - `close_call` in every node where a call can end, its enums cut down to that node's outcomes;
   - a transition on the close result into a silent end node.
   Take every URL, field and enum from the tool API file. Bake `customer_id` with
   `"default": "{{customer_id}}"`. Use `maxRetries: 0` on tools that write.

5. **Lint** and fix until there are no errors. Read every warning and fix the ones that matter:

   ```bash
   python $SKILL/scripts/lint_workflow.py out/<slot>.workflow.json --openapi <tool API file>
   ```

6. **Validate and save.**

   ```bash
   python -c "import freya,json,sys; print(freya.validate_workflow(sys.argv[1], json.load(open(sys.argv[2]))))" <slot> out/<slot>.workflow.json
   python -c "import freya,json,sys; print(json.dumps(freya.save_workflow(sys.argv[1], json.load(open(sys.argv[2])))))" <slot> out/<slot>.workflow.json
   ```

   The same slot updates the same workflow and publishes it. Then check that it starts, with one
   chat turn (seconds, no simulation):

   ```bash
   python -c "import freya,json,sys; r=freya.api('POST','/api/v2/chat/message',{'workflowId':sys.argv[1],'message':'Hello?','customerVariables':{'customer_id':'c_test','first_name':'Dana','last_name':'Fisher','title':'Ms','now':'2026-10-14T11:00'}}); print(r.get('response')); freya.api('POST','/api/v2/chat/end',{'callId':r.get('callId')})" <workflow_id>
   ```

   The first line must be the brief's opening, with the placeholders filled. A 500 means the
   workflow cannot start a call: fix that before anything else.

   **Chat turns cost the team's platform credit. Run this check once, and once more only after a
   fix for a 500 or a wrong opening line. Never more than three chat turns in a whole build.** Do
   not use chat to explore other paths of the call:
   - Chat may skip a code node that is the initial node, so values it computes can be empty in
     chat. Simulations run it (verified by the kit's working builder). Do not restructure the
     workflow because of this: an initial code node is correct.
   - `c_test` is not a customer of the mock bank, so every bank tool fails in chat. A failing
     tool in chat says nothing about the workflow.
   - What chat cannot show, the local checks (step 3) and the lint (step 5) must cover.

7. **Practice run, only where practice customers exist.** The kit's practice customers belong to
   the kit's briefs (`brief-a`, `brief-b`). For those, run them in the foreground and wait:

   ```bash
   python tools/run_cases.py <agent_id> --brief A --out results/<slot>.json
   ```

   (`--brief B` when you were given Brief B.) Final customers talk like people: when time allows,
   add `--style pieces` or `--style in_words` to a run. A run takes 3 to 11 minutes. Never start it in the
   background and never end your turn while it runs: the builder stops when you stop.
   For any other brief there are no practice customers on the mock bank, and the kit's customers
   follow other rules. Do not run them; steps 3, 5 and 6 are your tests.

8. **Fix what failed**, at most once or twice, as time allows. First rule out the platform: if
   the transcript shows tool errors such as "Failed to reach snekbox", "Cannot connect to host" or
   a 5xx on many tools at once, the platform had an outage. Do not change the design for that;
   if time allows run the practice customers once more, else finish. For each FAIL line, find the rule
   in your spec, then find why the agent broke it. The transcript is in
   `freya.get_call(call_id)["messages"]`; the call ids are in the `--out` file. Fix the cause in
   the build script, not the symptom in one prompt: a missing sentence goes into a fixed line or a
   post-hook, a wrong date into the code facts, a wrong outcome into the enum and the description
   of `close_call`, a leak into the structure (which node knows what). Re-run steps 4 to 6.

9. **Export and finish.**

   ```bash
   python -c "import freya,json,sys; print(freya.export_workflow(sys.argv[1], sys.argv[2]))" <workflow_id> out/<slot>.export.json
   ```

   End with one line: `workflow_id`, `agent_id`, steps lint/validate/chat passed, and the last
   practice result if there was one.

## Rules

- Create and change files with the Write and Edit tools. A long file written through a shell
  heredoc breaks on quotes and backticks and costs a retry.
- Never edit the agent on the platform by hand. Change the build script and save again.
- Leave `agent_config` out. Do not change the agent model.
- `examples/base-agent.json` is an export: it shows the JSON shape, not a design to copy. Do not
  copy its `null` fields, its positions or its end-of-call `close_call`. Close with a node tool as
  in `references/architecture.md`.
- For every special situation in the brief, check whether it applies before verification too (a
  request for a human, refusing to talk, a scam question). If it does, the early nodes need the
  tool and the outcome for it.
- The agent may call only the bank's tool API. Code nodes and hooks are allowed and expected.
- When a tool call fails, the agent says so. It never says something is recorded when it is not.
- Prefer rules in structure (nodes, transitions, enums, code, fixed lines) over rules in prompts.
  A customer that passes once can fail the next time; structure does not drift.
- One FAIL is not proof of a bad rule and one PASS is not proof of a good one. Read the transcript
  before you change anything.

## Bundled files

| File | Use |
|---|---|
| `references/architecture.md` | The workflow shape, why, and JSON recipes for each part. Read before step 4 |
| `references/reading-a-brief.md` | What to extract from a brief, raw bank material included. Read for step 2 |
| `scripts/calendar_lib.py` | Business-day helpers that go in front of every code-node snippet |
| `scripts/build_code.py` | Joins helpers and snippet, checks for doubled braces and syntax, runs it on example vars |
| `scripts/lint_workflow.py` | Static checks for the mistakes the platform accepts silently |
