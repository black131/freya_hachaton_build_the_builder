# A workflow shape that works for collection calls

Read this before you write the workflow. It is a pattern, not the answer: every prompt, value,
outcome, sentence and field comes from the brief and the tool API file you were given. The node
names below are suggestions. Nothing here belongs to one bank.

## Contents

1. The graph
2. Why it is shaped this way
3. Recipes: code node, account fetch, tool with a post-hook, close and end, greeting fork
4. Prompt rules that decide pass or fail

## 1. The graph

```text
setup (code, passthrough)          computes date facts from `now` and the brief's calendar
  -> greet (conversation)          fixed opening line; extracts who is on the line
       -> third_party (conversation)   no reason for the call is given; callback or close
       -> identity (conversation)      security questions, one tool call per answer
            -> fetch_account (api_request, passthrough)   get_account, always, no model choice
                 -> account (code, passthrough)           per-product facts: band, deadline, floor, attempts
                      -> collect (conversation)          state the debt, negotiate, read back, record
  every conversation node that may end the call has close_call
       -> end (end_call)             entered when close_call returned ok
```

Add nodes when the brief has a stage with strict rules of its own. Merge when two stages share
their rules and their tools. A brief for one product and a brief for three products use the same
graph: the difference is in `collect`'s prompt and in the account facts.

## 2. Why it is shaped this way

- **The agent model is small.** It runs on the event's own model, not on yours. It follows short,
  concrete instructions and ready-made facts well. It does date arithmetic, counting and rule
  lookup badly. So every number the agent needs is computed in code and handed to it as text.
- **Routing reads transitions, not prompts.** "Move on after verification" in a prompt does
  nothing. A transition on `verify_identity_response.data.all_verified` does.
- **A tool the model may skip will be skipped some of the time.** `get_account` has no decision in
  it, so it runs as a `pre_action`. Tools that depend on the customer (`create_promise`,
  `transfer_to_agent`, `close_call`) stay with the model, and a post-hook tells the model what the
  result means.
- **Three runs must all pass.** Anything left to the model's judgement fails one run in three.
  Prefer: fixed spoken lines (`tts`) for sentences the brief dictates, enums on every tool field
  that has allowed values, per-node enums that only allow the outcomes possible in that node.
- **Disclosure is structural.** Only `collect` knows the account. `greet`, `third_party` and
  `identity` have no account facts in their prompts and no `get_account` tool, so they cannot leak.

## 3. Recipes

All JSON below is the shape the platform accepts (see docs/workflow-format.md and
docs/tools-and-code.md). Build the JSON with a Python script and `json.dump`, never by hand:
code and hooks are long strings that need escaping.

### 3.1 Code node (calendar and account facts)

Write the snippet in its own file, test it with `scripts/build_code.py`, then embed the output.

```python
src = subprocess.run([sys.executable, SKILL + "/scripts/build_code.py", "out/setup_snippet.py", "--out", "out/setup_code.txt"], check=True)
code = open("out/setup_code.txt", encoding="utf-8").read()
node = {
  "name": "setup", "node_type": "code", "passthrough": True,
  "passthrough_default_transition": "greet", "on_enter": {"type": "silent"},
  "pre_actions": [{"type": "function", "function": {"name": "code_exec", "handler": "__function__:code_exec",
      "parameters": {"type": "object", "properties": {
          "code": {"type": "string", "default": code},
          "timeout_ms": {"type": "number", "default": 10000}}}}}],
  "transitions": [{"target_node": "greet", "description": "always", "condition": {"operator": "always"}}],
}
```

A snippet defines `RULES` from the brief and writes text facts. Example shape (the values here
are invented, take yours from the brief):

```python
RULES = dict(weekend=[5, 6], holidays=["2031-04-02"],
             bands=[dict(name="soft", lo=1, hi=10, deadline=dict(business_days=5), attempts=1)])
try:
    cal = Calendar(RULES["weekend"], RULES["holidays"])
    now = parse_now(vars.get("now")); today = now.date()
    dl = cal.add_business_days(today, 5)
    vars["date_facts"] = "Today: " + spoken(today) + "\n" + cal.table(today, (dl - today).days + 8, deadline=dl)
except Exception as e:
    vars["date_facts"] = "Date facts are not available."
```

What to put in the facts: today and its weekday, whether today is a business day, the next
business day, every date the brief names by rule (this week's last business day, a deadline per
band, a callback window), and a day-by-day table that runs past the latest deadline. A model that
can look a date up does not have to compute it. Write each deadline next to the band it belongs to
and say which days it includes ("on or before").

Account facts are one line per product, in the order the API returned them, with everything the
negotiation needs: id, how to say the product (the brief's wording), past-due amount, days late,
band, deadline, floor, number of attempts, and the date and amount of each attempt. Read the
product list with `read_list(vars, "products", "get_account_response.data.products",
"<fetch node>_response.data.products")`: the stored form of a list is not confirmed.

**Give answers, not statuses, for dates.** Seen in a practice run: the table said "26 October:
holiday, next business day 27 October" and the deadline was given above it, yet the agent offered
the deadline instead of the 27th. It had to combine the holiday rule and the deadline rule itself.
Once the products are known (in the account snippet), write a table of what to SAY for each day,
per product, with `answer_table`. The function you pass encodes the brief's date rules in order:

```python
def answer(d):
    parts = []
    for p in plan:                       # plan: per product, with its deadline, from the brief's band table
        if d < today:                    parts.append(p["id"] + ": in the past, ask for another day")
        elif d > p["deadline"]:          parts.append(p["id"] + ": after its deadline, say the latest date is " + spoken(p["deadline"]) + " and offer it")
        elif not cal.is_business_day(d): nd = cal.next_business_day(d); parts.append(p["id"] + ": not a business day, offer " + spoken(nd) + " (" + nd.isoformat() + ")")
        else:                            parts.append(p["id"] + ": accept")
    return "; ".join(parts)
vars["date_answers"] = answer_table(cal, today, (latest_deadline - today).days + 10, answer)
```

The branches above only show the form: take their order and content from the brief (for example
whether a non-business day whose next business day passes the deadline gets the deadline). In the
prompt, say: "When the customer names a day, find it in the date answers and do exactly what its
line says." When an earlier row of the decision table leads to a date (a vague period, then a
named day), say that the named day goes through the date answers like any other.

Test each snippet on realistic `vars` before you save: `python scripts/build_code.py snippet.py
--run vars.json --expect date_facts`. Build `vars.json` from a practice case (its `now` and
products) or from the brief's own examples. Check every date against the brief by hand once.

### 3.2 Fetch the account without a model decision

```json
{
  "name": "fetch_account", "node_type": "api_request", "passthrough": true,
  "passthrough_default_transition": "account", "on_enter": {"type": "silent"},
  "pre_actions": [{"type": "function", "config": {"timeoutMs": 12000, "maxRetries": 2},
    "function": {"name": "get_account", "handler": "__function__:api_call", "description": "Get the late products.",
      "parameters": {"type": "object", "properties": {
        "url": {"type": "string", "default": "<server>/get_account"},
        "method": {"type": "string", "default": "POST"},
        "headers": {"type": "object", "properties": {"Content-Type": {"type": "string", "default": "application/json"}}},
        "body": {"type": "object", "properties": {"customer_id": {"type": "string", "default": "{{customer_id}}"}}, "required": []}}}}}],
  "response_mapping": [{"path": "data.products", "variable": "products"}],
  "transitions": [{"target_node": "account", "description": "always", "condition": {"operator": "always"}}]
}
```

### 3.3 A tool with a post-hook that tells the model what happened

Bare results such as `{"ok": true}` make the small model fall silent or ignore a failure. A
post-hook adds one instruction line to the result. Write the line from the brief: what the result
means and the exact next thing to say or call.

```python
POST = """try:
    if isinstance(result, dict):
        result.pop('header', None)
        d = result.get('data')
        if not isinstance(d, dict):
            d = dict()
            result['data'] = d
        ok = d.get('ok') is True and int(result.get('status_code') or 200) < 400
        if ok:
            d['what_to_do_next'] = 'RECORDED. Now say: ... (the sentence the brief requires).'
        else:
            d['what_to_do_next'] = 'NOT recorded. Do not say it is recorded. Call create_promise once more with exactly the same values. If this already was the second try, say that you could not record it and ... (brief rule).'
except Exception:
    pass
"""
```

**Treat "already exists" as success.** Write tools are not idempotent. Seen in a practice run:
the agent called the record tool, the customer said "okay" while the call was in flight, the new
turn called the same tool again, the bank answered "this product already has a promise", and the
hook reported a failure. The agent then told the customer it could not record a promise that was
recorded, and noted a service error. In every write tool's post-hook, read the API's error text:
when it says the record already exists, report it as RECORDED and tell the model not to call the
tool again for that item. Do not count it as a failed try.

Note `dict()` in place of an empty literal: a nested literal can end in a doubled brace. For
`verify_identity`, branch on the API's own fields (for example a verified flag, the answers left,
a hint, an all-verified flag) and say exactly which question to ask next, whether to repeat it,
and when to stop and close.

Put the line `After every tool result, read what_to_do_next and do it in the same turn. Never end
a turn with nothing said.` into the system prompt.

### 3.4 close_call, per node, and the end node

Give `close_call` to every conversation node in which the call can end, and restrict its enum to
the outcomes and reasons possible in that node. A greeting node cannot close as a promise; a
collection node cannot close as not verified. Describe each allowed value with the brief's rule
in the field description.

```json
"body": {"type": "object", "required": ["outcome"], "properties": {
  "customer_id": {"type": "string", "default": "{{customer_id}}"},
  "outcome": {"type": "string", "enum": ["<only this node's outcomes>"], "default": "{{outcome}}", "description": "<when each one applies, from the brief>"},
  "reason": {"type": "string", "enum": ["<only this node's reasons>"], "default": "{{reason}}", "description": "<the brief's table rows for this node>"}}}
```

If the outcome table has outcomes without a reason, drop `reason` for them in a pre-hook:

```python
PRE = """try:
    b = config.get('body')
    if isinstance(b, dict) and b.get('outcome') in ('<outcomes without reason>',):
        b.pop('reason', None)
except Exception:
    pass
"""
```

Route to the end node on the result, from every node that has `close_call`:

```json
{"target_node": "end", "description": "the call was closed", "condition": {"logic": "or", "conditions": [
  {"variable": "close_call_response.data.ok", "operator": "equals", "operand": "true"},
  {"variable": "close_call_response.data.ok", "operator": "equals", "operand": "True"}]}}
```

```json
{"name": "end", "node_type": "end_call", "on_enter": {"type": "silent"}, "disable_inactivity_monitor": true, "transitions": [],
 "terminal": {"type": "function", "function": {"name": "call_closed", "handler": "__function__:end_call",
   "parameters": {"type": "object", "properties": {"message_mode": {"type": "string", "default": "none"}}}}}}
```

The agent says thank you and goodbye in the same turn as the `close_call` call (if the brief asks
for it). The end node hangs up silently.

### 3.5 Greeting: a fixed line and a fork on an extracted enum

Say the brief's opening with `on_enter: {"type": "tts", "text": "..."}` so it is the same every
time. Fork on an enum, not on several competing intents:

```json
"extraction_schema": [{"name": "line_status", "type": "string", "min_confidence": 0.6,
  "enum_values": ["customer", "someone_else", "<other cases the brief names, e.g. wrong number>", "unclear"],
  "description": "Who answered, judged ONLY by the brief's confirmation rule: <copy the rule, e.g. which words count as yes>."}],
"transitions": [
  {"target_node": "identity", "description": "the customer confirmed", "condition": {"logic": "or", "conditions": [{"variable": "line_status", "operator": "equals", "operand": "customer"}]}},
  {"target_node": "third_party", "description": "someone else answered", "condition": {"logic": "or", "conditions": [{"variable": "line_status", "operator": "equals", "operand": "someone_else"}]}}
]
```

Cases that end the call at once (wrong number, deceased, unclear twice) stay in `greet` and close
there with `close_call`. Answer questions (robot, scam) in `greet` without moving on.

A variable keeps its value for the whole call. If a later node must not see an earlier value,
extract a different name there.

### 3.6 Sentences built from data, spoken as fixed lines

When the brief dictates what to say about the account (product names, amounts, days late, the
first question), build the whole sentence in the account code node and speak it with
`on_enter: {"type": "tts", "text": "{{debt_statement}}"}` in the negotiation node. The model then
cannot leave out a product, misread an amount or ask the wrong first question. Give the snippet a
fallback sentence for an empty product list.

### 3.7 Name clashes with model-filled fields

A tool field declared as `"default": "{{date}}"` is filled by the model only while no variable
`date` exists. If any node extracts or writes `date`, the field is baked from that value and the
model never sees it. Give extracted and code-written variables names that no tool field uses
(`wanted_date`, not `date`). The lint warns about this.

### 3.8 Recording without inviting the customer to speak

Do the read-back, the confirmation and the recording in the same conversation node, or move to a
recording node with `on_enter: {"type": "silent"}`. Never enter a node that must call tools at once
with a filler line such as "One moment please": the customer answers it, the answer starts a new
turn while the tool call is in flight, and the tool is called twice. Fillers may also be spoken in
the workspace's own language instead of the call's language (seen: an English filler came out in
Turkish). Every spoken line must come from the brief or from your prompts, in the brief's language.

### 3.9 Gate the write tools by structure

Seen in a practice run: the customer said "I'll pay the credit card tomorrow, not the other two",
and in the same turn the agent recorded the promise with no read-back, noted the other two products
as refused with no persuasion attempt, and closed the call. The prompt had every rule; the model
skipped them because the tools were at hand. Rules in prompts drift; structure does not.

- The negotiation node has no tool that records a promise or a note. It can only talk (and
  transfer or close where the brief allows that before an agreement).
- Extract a state in the negotiation node, for example `deal_state` with values `confirmed` (the
  customer said yes to the full read-back), `all_ended` (every product ended without an agreement,
  and for each refused product every attempt listed in the account facts was said and refused;
  one refusal of a product that has two attempts is not an end) and `continue`. Describe each value strictly.
- A transition on that state leads to a recording node with `on_enter: {"type": "silent"}` (see
  3.8). That node holds the record and note tools, `close_call`, and a prompt that records exactly
  what was read back, notes what ended without a promise, then closes.
- One tool call per message, and `close_call` only after every record and note result arrived.

### 3.10 Answers given in pieces

Final customers give numbers and dates in two parts ("forty four" ... "ten"), correct themselves,
and say them in words. Seen in a practice run: the agent asked for "all four digits" after each
part, five times, and never put "forty four" and "ten" together. In the identity prompt (and
wherever a number or date is collected):
- A partial answer is not wrong and not an answer: say "Yes?" or "And the rest?" and wait. Do not
  call the check tool on a part.
- Put the parts from consecutive turns together, in order, before calling the tool ("forty four",
  then "ten" is 4410; "nineteen October", then "nineteen eighty three" is 1983-10-19).
- When the customer corrects themselves ("the 21st, sorry, the 20th"), use the corrected value.

## 4. Prompt rules that decide pass or fail

- **Sentences the brief dictates go in verbatim**, in quotes, in the node where they are said, and
  in the post-hook line of the tool after which they are said. The judge checks them word by word
  in spirit: a paraphrase of a required sentence often fails.
- **Words the brief forbids before a point** ("collections", "debt", a product) appear in a list
  in every prompt before that point. Do not write them anywhere else in those prompts, not even
  as examples.
- **Count limits in words the model can follow**: "You may make ONE persuasion attempt for this
  product. It is: <amount> on <date>." is better than "attempts depend on the band".
- **Give the agent the decision table, not the reasoning.** For each thing a customer can say
  (a date, a vague period, an amount, too much, a refusal, hardship, already paid, dispute, plan,
  human, scam, robot, wrong person), write the one response the brief requires, in brief order of
  priority. Say which rule wins when two apply.
- **Never ask what the brief forbids asking** (for example how much the customer can pay). Name
  the forbidden question in the prompt.
- **One question per turn, one tool per message, speak after every tool result.**
- **Read-back**: list what it must contain (product, amount, date, every product at once if the
  brief says so) and the exact confirmation question. Give it as a template in future tense, for
  example "To confirm: <product>, <amount>, on <date>. <confirmation question>". Seen in a practice
  run: the agent said "I have recorded a payment ... Do you confirm?" before any tool call, which
  fails the honesty check. Name the words that are forbidden until the record tool returned ok
  ("recorded", "booked", "saved", "registered", "set up", "done").
- **Honesty**: say it is recorded only after a successful result, and never claim an action that
  was not a tool call. After a successful record, say plainly that it is recorded ("Your promise is
  recorded.") before any sentence the brief requires; after a failed try that succeeded on retry,
  this is how the customer learns it worked.
- **Attempts before giving up, per product**: a refusal does not end a product until the brief's
  persuasion attempts for that product are used. Seen in a practice run: the customer refused two
  of three products in one sentence and the agent noted both as refused at once, skipping the
  attempts the brief required. Write it in the prompt as a sequence: "For each product the customer
  refuses: make attempt 1 as written in the account facts; if refused again and the product has
  attempt 2, make it; only then record the refusal (note, outcome)." When several products are
  refused together, go through them one at a time in the account order.
  Seen again, with amounts said in words: the agent made one attempt on a product that had two.
  So write the attempts in the account facts as numbered, ready-to-say sentences, for example
  "Attempt 1: ask for <full amount> on <date>. Attempt 2 (REQUIRED after attempt 1 is refused):
  offer <floor> on <deadline>.", and give the product a line "This product ends only after
  attempt <n> is refused." In the negotiation prompt: before you treat a product as ended, check
  in the account facts that every attempt listed for it was said and refused.
- **Keep prompts short.** Every rule in a prompt costs attention. Put rules where they apply, not
  in every node.
