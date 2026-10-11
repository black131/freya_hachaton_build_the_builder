# EXAMPLE ONLY: the build script that passed every practice customer of the kit's Brief A + B
# (4 separate runs: plain speech, answers in pieces, self-corrections, 3 repetitions).
#
# Use it for the SHAPE: the node graph (setup -> greet -> third_party | identity -> fetch_account
# -> account -> collect -> end), entry types, the hook() helper, the per-node close_call enums,
# and the STRICT ORDER block in COLLECT_TASK. Recording happens in collect itself.
#
# Every sentence, value, word list, outcome, reason and rule below belongs to that one brief.
# Do NOT copy any of it into another brief's agent. Write yours from your own spec.
#

import json, subprocess, sys, os

SKILL = ".claude/skills/build-phone-agent"
SERVER = "https://freya-bank-mock.freyavoice.workers.dev/v1"


def code_of(snippet, out):
    subprocess.run([sys.executable, SKILL + "/scripts/build_code.py", snippet, "--out", out], check=True)
    return open(out, encoding="utf-8").read()


SETUP_CODE = code_of("out/brief-b_setup_snippet.py", "out/brief-b_setup_code.txt")
ACCOUNT_CODE = code_of("out/brief-b_account_snippet.py", "out/brief-b_account_code.txt")


def code_node(name, code, target):
    return {"name": name, "node_type": "code", "passthrough": True, "passthrough_default_transition": target,
            "on_enter": {"type": "silent"},
            "pre_actions": [{"type": "function", "function": {"name": "code_exec", "handler": "__function__:code_exec",
                "parameters": {"type": "object", "properties": {
                    "code": {"type": "string", "default": code},
                    "timeout_ms": {"type": "number", "default": 10000}}}}}],
            "transitions": [{"target_node": target, "description": "always", "condition": {"operator": "always"}}]}


def api_tool(name, desc, body_props, required, retries=0, post="", pre="", timeout=12000):
    props = {"customer_id": {"type": "string", "default": "{{customer_id}}", "description": "The customer id."}}
    props.update(body_props)
    t = {"type": "function", "config": {"timeoutMs": timeout, "maxRetries": retries},
         "function": {"name": name, "handler": "__function__:api_call", "description": desc,
                      "parameters": {"type": "object", "properties": {
                          "url": {"type": "string", "default": SERVER + "/" + name},
                          "method": {"type": "string", "default": "POST"},
                          "headers": {"type": "object", "properties": {"Content-Type": {"type": "string", "default": "application/json"}}},
                          "body": {"type": "object", "properties": props, "required": required}}}}}
    if post:
        t["post_process_code"] = post
    if pre:
        t["pre_process_code"] = pre
    return t


def hook(body):
    lines = ["try:", "    if isinstance(result, dict):", "        result.pop('header', None)",
             "        d = result.get('data')", "        if not isinstance(d, dict):", "            d = dict()",
             "            result['data'] = d",
             "        ok = d.get('ok') is True and int(result.get('status_code') or 200) < 400",
             "        err = str(d.get('error') or result.get('message') or '').lower()"]
    lines += ["        " + l for l in body.strip("\n").split("\n")]
    lines += ["except Exception:", "    pass", ""]
    return "\n".join(lines)


VERIFY_POST = hook("""
left = d.get('wrong_answers_left')
if d.get('all_verified') is True or str(d.get('all_verified')) in ('true', 'True'):
    d['what_to_do_next'] = 'IDENTITY VERIFIED. Say only: Thank you, that is confirmed. Nothing else.'
elif d.get('hint') == 'day_month_swapped':
    d['what_to_do_next'] = 'Not counted as wrong. Ask the customer to say their date of birth again with the month as a word, for example the 3rd of June 1987.'
elif not ok and d.get('verified') is None:
    d['what_to_do_next'] = 'The answer could not be read and was NOT counted. Ask the same question again; for a date ask for day, month as a word, and year.'
elif d.get('verified') is True:
    d['what_to_do_next'] = 'Correct. Now ask the second question: the last four digits of the phone number on file.'
elif left is not None and int(left) <= 0:
    d['what_to_do_next'] = 'CHECK FAILED, no tries left. Do not mention any account, amount or reason for the call. Say they can use the Freya Bank mobile app or visit a branch, thank them, say goodbye, and call close_call with outcome not_verified and reason failed.'
else:
    d['what_to_do_next'] = 'Wrong answer. Ask the SAME question once more, without saying what is on file.'
""")

PROMISE_POST = hook("""
if ok or 'already' in err or 'exists' in err:
    d['ok'] = True
    d['what_to_do_next'] = 'RECORDED for this product_id. Never call create_promise again for this product. If another agreed promise from the read-back is not recorded yet, call create_promise for it now. When all are recorded, say exactly: "You will receive a text message confirming this promise." Then, for any product without a promise, call add_note; then close.'
else:
    d['what_to_do_next'] = 'NOT recorded. Do not say it is recorded. If this was the FIRST try for this product, call create_promise again now with exactly the same values. If it was the SECOND failed try, say you could not record the promise for this product, call add_note for it with reason service_error, then continue with the other products.'
""")

NOTE_POST = hook("""
if ok or 'already' in err or 'exists' in err:
    d['what_to_do_next'] = 'Note saved. Never note this product again. Continue with the next product in order; if every product is handled, give the closing words and call close_call per the closing rule.'
else:
    d['what_to_do_next'] = 'The note failed. Call add_note once more with the same values.'
""")

TRANSFER_POST = hook("""
if ok:
    d['what_to_do_next'] = 'TRANSFERRED. Do NOT call add_note or create_promise. Say thank you and goodbye, then call close_call with outcome transferred and reason restructuring (queue restructuring), human (queue general) or support (queue support).'
else:
    d['what_to_do_next'] = 'The transfer failed. Call transfer_to_agent once more with the same queue.'
""")

CALLBACK_POST = hook("""
if ok:
    d['what_to_do_next'] = 'Callback booked. Thank them, say goodbye, call close_call with outcome not_reached and reason callback.'
else:
    d['what_to_do_next'] = 'NOT booked. Call schedule_callback once more with the same values. If it fails again, say it could not be booked, thank them and close with not_reached and reason no_callback.'
""")

CLOSE_POST = hook("""
if ok:
    d['what_to_do_next'] = 'The call is closed. Say nothing more.'
else:
    d['what_to_do_next'] = 'close_call failed. Call close_call once more with the same values.'
""")

CLOSE_PRE = """try:
    b = config.get('body')
    if isinstance(b, dict) and b.get('outcome') in ('promise', 'paid'):
        b.pop('reason', None)
except Exception:
    pass
"""


def close_tool(outcomes, reasons, desc):
    props = {"outcome": {"type": "string", "enum": outcomes, "default": "{{outcome}}", "description": desc},
             "reason": {"type": "string", "enum": reasons, "default": "{{reason}}", "description": "The reason that goes with the outcome. Leave empty for promise and paid."}}
    return api_tool("close_call", "End the call. CALL it exactly once, as the very last tool call, in the same turn as your thank-you and goodbye. " + desc,
                    props, ["outcome"], retries=0, post=CLOSE_POST, pre=CLOSE_PRE)


def transfer_tool(queues, desc):
    return api_tool("transfer_to_agent", desc, {"queue": {"type": "string", "enum": queues, "default": "{{queue}}", "description": "restructuring = new payment plan or lower instalments; general = the customer insists on a human; support = hardship and accepted support."}},
                    ["queue"], retries=0, post=TRANSFER_POST)


END_T = {"target_node": "end", "description": "the call was closed", "condition": {"logic": "or", "conditions": [
    {"variable": "close_call_response.data.ok", "operator": "equals", "operand": "true"},
    {"variable": "close_call_response.data.ok", "operator": "equals", "operand": "True"}]}}

FORBID = 'Before identity is verified NEVER say any of these words or hint at them: "collections", "debt", "payment", "owe", "late", "overdue", "account", "loan", "credit card", "product". If asked what the call is about, say only that it is a personal matter for {{title}} {{last_name}}.'

SYSTEM = """You are Freya Bank's digital assistant on an outbound phone call. Speak English. Be brief and polite: one or two short sentences per turn, ONE question per turn.
After every tool result, read what_to_do_next and do it in the same turn. Never end a turn with nothing said. Call one tool at a time.
Address the customer as {{title}} {{last_name}}.
If asked whether you are a robot or an AI: say you are Freya Bank's digital assistant, then continue with your current question.
If asked whether this is a scam: say they can verify this call by phoning Freya Bank's customer service number, then continue with your current question.
If the person asks for a human: the first time ask whether you can help them first. If they insist, call transfer_to_agent with queue general, then close as transferred with reason human.
A question you cannot answer from your facts or tools: say you do not have that information. Never invent figures, dates or reasons.
Never claim an action happened unless its tool returned ok. Never offer a discount, waiver, instalment plan or any other term.
Before close_call always thank the customer and say goodbye, in the same turn as the close_call call. close_call is always the last tool call."""

OPENING = "Hello, this is Freya Bank's digital assistant calling. This call is recorded. Am I speaking with {{title}} {{last_name}}?"

GREET_TASK = FORBID + """
You asked whether you are speaking with {{title}} {{last_name}}. No tool call except close_call and transfer_to_agent is allowed here.
- Only "yes", "that's me", "speaking" or the customer's own name counts as confirmation. "Hello", "go ahead", "who is this" do NOT.
- If it is not a confirmation (or they asked a question; answer it first per the rules), ask again exactly: "Am I speaking with {{title}} {{last_name}}?" This is your second and last ask. If still unclear after the second ask: thank them, say goodbye, call close_call with outcome not_reached, reason unclear.
- If they say this number does not belong to that person: apologise, say goodbye, close_call not_reached / wrong_number.
- If they say the customer has died: say "I am sorry for your loss." Ask nothing else, say goodbye, close_call not_reached / deceased.
- If the person refuses to talk twice: thank them, goodbye, close_call not_verified / declined."""

THIRD_TASK = FORBID + """
Someone other than {{title}} {{last_name}} is on the line. Do not say why you are calling. Do not answer any question about the customer or any money matter, even if they offer to pay; say only that it is a personal matter. Ask when {{title}} {{last_name}} can be reached.
{{callback_facts}}
- If they name a day and time inside the allowed slots: call schedule_callback with date YYYY-MM-DD and time HH:MM (24h). Then thank, goodbye, close_call not_reached / callback.
- If the day or time is outside the slots: ask ONCE for another time, naming the allowed window (today or the next business day, between 10:00 and 19:00). If the second answer is also outside, do not schedule: thank, goodbye, close_call not_reached / no_callback. Also no_callback if they give no time.
- If they say the number does not belong to the customer: close_call not_reached / wrong_number.
- If they say the customer has died: say "I am sorry for your loss.", ask nothing else, goodbye, close_call not_reached / deceased."""

IDENTITY_TASK = FORBID + """
The customer confirmed who they are. Check identity with two security questions, one at a time.
1. Say that for security you need to ask two questions, and ask for their date of birth. When they answer, call verify_identity with field date_of_birth and answer as YYYY-MM-DD. A date given only as numbers is day, then month, then year (03/06/1987 = 1987-06-03). Convert spoken dates yourself.
2. Then ask for the last four digits of the phone number on file and call verify_identity with field phone_last4 and the four digits.
Follow what_to_do_next after each result. Never reveal what is on file.
- Customers often give an answer in PIECES over several turns ("nineteen October" then "nineteen eighty three"; "forty four" then "ten" = 4410). Combine the pieces of the current answer. If the answer is not complete yet, reply only "Yes, go on." (do NOT repeat the question). As soon as you have a full date or four digits, call verify_identity.
- If they do not want to answer, or ask what the call is about instead of answering: explain ONCE that the questions protect their account and ask again. If they refuse again or ask again: thank, goodbye, close_call not_verified / declined.
- A request for a human follows the system rule (transfer queue general, close transferred / human)."""

COLLECT_TASK = """Identity is verified. You have already said this aloud: "{{debt_statement}}"

ACCOUNT FACTS (one line per product, in order):
{{account_facts}}

{{date_facts}}
DATE ANSWERS: when the customer names a day, find it here and do exactly what its line says for each product:
{{date_answers}}

STRICT ORDER OF THE CALL (never skip a step):
1. Negotiate every product, one at a time, in account order, until each has an agreed promise or its persuasion attempts are all used (or it is paid/dispute/hardship).
2. Read ALL agreed promises back in ONE message ending with "Do you confirm?" and WAIT for the customer's answer.
3. Only after a clear yes: create_promise, one per agreed product.
4. add_note for each product without a promise.
5. Thank, say goodbye, and call close_call in that same message.
NEVER call create_promise in the turn where the customer agrees to a date or amount: first do step 2 and wait.
Example: "I'll pay the card tomorrow, not the other two" = card agreed for tomorrow (check DATE ANSWERS); then the second product: make its attempt 1; if refused and it has attempt 2, make attempt 2; then the third product the same way; only then step 2.

HOW TO NEGOTIATE
- The question about paying today is asked ONCE for all products (already asked). If yes for all: the promise is the full amount of every product dated today.
- If not all today: go through the products one by one in the order above. For each product start at its attempt 1. Never ask about today again.
- Always ask for the full past-due amount first. NEVER ask "how much can you pay?" - you propose every amount.
- Customer names a date: use DATE ANSWERS. A vague period ("next week", "end of month", "when my salary comes"): ask once for the exact day; a named day then goes through DATE ANSWERS; if still none, propose that product's deadline.
- "Next <weekday>" = that weekday in the following calendar week; "this <weekday>" = in the current week.
- If the customer names ONE date for everything and it is after one product's deadline, that product gets its own deadline and the others keep the named date; say so in the read-back.
- Full amount too much: offer the product's floor once and say the rest stays overdue. Amount from floor to full (inclusive): accept. Below floor: say it cannot be recorded and offer the floor once.
- A proposed date or amount is never a refusal.
- Flat refusal, non-answer, refusing the floor, refusing the deadline offer: that uses one persuasion attempt for that product. Make the product's next attempt exactly as written in ACCOUNT FACTS. When its attempts are used up, stop (never repeat a refused offer): that product is refused. When several products are refused in one sentence, still go through them one at a time with their attempts.
- Illness, death in the family or job loss: one short sentence of sympathy, NO persuasion; offer to connect them with the customer support team. Accept: transfer_to_agent queue support, close transferred / support. Decline: the remaining unpromised products get note hardship. If they still name a date or amount themselves, handle it normally.
- "I already paid" (this past-due amount) for a product: say payments can take one business day to appear; no promise for it; it gets note paid; continue with the other products.
- "Not mine" / "never had it" / "closed or paid off in the past": do not argue; no promise; note dispute; continue with the others.
- New payment plan or lower instalments: do not describe a plan. Do NOT record any agreed-but-unrecorded promise. Call transfer_to_agent queue restructuring, close transferred / restructuring.
- On ANY transfer never call add_note, before or after it.
- Customer says twice they do not want to talk: remaining products get note refused, then close.
- Recorded promises cannot be changed or cancelled; they can change it in the mobile app.

READ-BACK AND RECORDING
- When every product is settled (promise agreed or no promise), read ALL agreed promises back together in ONE message in future tense: "To confirm: <product> <amount> on <weekday day month>; <next product> ... Do you confirm?" Do not use the words recorded, booked, saved, registered, set up or done before create_promise returned ok.
- If they change a date or amount, check it again and read everything back again.
- After a clear yes: call create_promise once per agreed product (product_id, amount as a number, date YYYY-MM-DD), one at a time, in order. Follow what_to_do_next.
- Then for EACH product without a recorded promise call add_note with its product_id and reason (refused, hardship, dispute, paid, service_error). Also when no product has a promise.

CLOSING (thank and say goodbye in the same turn as close_call)
- At least one promise recorded and no transfer: outcome promise.
- Transfer happened: outcome transferred with that transfer's reason.
- No promise recorded: if every product is noted paid, outcome paid; otherwise outcome no_promise with the reason of the FIRST product in account order whose note is not paid."""

WF = {
    "initial_node": "setup",
    "system_prompt": SYSTEM,
    "test_variables": {"customer_id": "c_test", "first_name": "Dana", "last_name": "Fisher", "title": "Ms", "now": "2026-10-14T11:00"},
    "nodes": {},
}
N = WF["nodes"]
N["setup"] = code_node("setup", SETUP_CODE, "greet")

N["greet"] = {
    "name": "greet", "node_type": "conversation", "on_enter": {"type": "tts", "text": OPENING}, "on_enter_first_entry_only": True,
    "task_message": GREET_TASK,
    "extraction_schema": [{"name": "line_status", "type": "string", "min_confidence": 0.6,
                           "enum_values": ["customer", "someone_else", "wrong_number", "unclear"],
                           "description": "Who answered. customer ONLY if the person said yes, that's me, speaking, or the customer's own name. someone_else if the person says they are someone else (a relative, colleague, etc.) or the customer is not available. wrong_number if the number does not belong to the customer. Otherwise unclear (hello, go ahead, who is this, questions)."}],
    "tools": [close_tool(["not_reached", "not_verified", "transferred"], ["unclear", "wrong_number", "deceased", "declined", "human"],
                         "not_reached/unclear: still unclear after the second ask. not_reached/wrong_number: not the customer's number. not_reached/deceased: customer has died. not_verified/declined: refuses to talk twice. transferred/human: after transfer_to_agent general."),
              transfer_tool(["general"], "Hand the call to a person. CALL it only when the person insists on a human after you asked once whether you can help.")],
    "transitions": [END_T,
                    {"target_node": "identity", "description": "the customer confirmed", "condition": {"logic": "or", "conditions": [{"variable": "line_status", "operator": "equals", "operand": "customer"}]}},
                    {"target_node": "third_party", "description": "someone else answered", "condition": {"logic": "or", "conditions": [{"variable": "line_status", "operator": "equals", "operand": "someone_else"}]}}],
}

N["third_party"] = {
    "name": "third_party", "node_type": "conversation", "on_enter": {"type": "llm"},
    "task_message": THIRD_TASK,
    "tools": [api_tool("schedule_callback", "Book a callback. CALL it only when the person gave a day and time inside the allowed callback slots.",
                       {"date": {"type": "string", "default": "{{cb_date}}", "description": "Callback date YYYY-MM-DD, today or the next business day only."},
                        "time": {"type": "string", "default": "{{cb_time}}", "description": "Callback time HH:MM, 24h, from 10:00 to 19:00."}},
                       ["date", "time"], retries=0, post=CALLBACK_POST),
              close_tool(["not_reached", "transferred"], ["callback", "no_callback", "wrong_number", "deceased", "human"],
                         "not_reached/callback: callback booked. not_reached/no_callback: no valid time after one re-ask. not_reached/wrong_number. not_reached/deceased. transferred/human: after transfer_to_agent general."),
              transfer_tool(["general"], "Hand the call to a person. CALL it only when the person insists on a human after you asked once whether you can help.")],
    "transitions": [END_T],
}

N["identity"] = {
    "name": "identity", "node_type": "conversation", "on_enter": {"type": "llm"},
    "task_message": IDENTITY_TASK,
    "tools": [api_tool("verify_identity", "Check one security answer. CALL it every time the customer answers a security question.",
                       {"field": {"type": "string", "enum": ["date_of_birth", "phone_last4"], "default": "{{field}}", "description": "date_of_birth for the first question, phone_last4 for the second."},
                        "answer": {"type": "string", "default": "{{answer}}", "description": "date_of_birth as YYYY-MM-DD (numbers only: day, month, year); phone_last4 as four digits."}},
                       ["field", "answer"], retries=1, post=VERIFY_POST),
              close_tool(["not_verified", "transferred"], ["failed", "declined", "human"],
                         "not_verified/failed: three wrong answers. not_verified/declined: refused the questions twice (or asked what the call is about twice). transferred/human: after transfer_to_agent general."),
              transfer_tool(["general"], "Hand the call to a person. CALL it only when the customer insists on a human after you asked once whether you can help.")],
    "transitions": [END_T,
                    {"target_node": "fetch_account", "description": "identity verified", "condition": {"logic": "or", "conditions": [
                        {"variable": "verify_identity_response.data.all_verified", "operator": "equals", "operand": "true"},
                        {"variable": "verify_identity_response.data.all_verified", "operator": "equals", "operand": "True"}]}}],
}

fetch = api_tool("get_account", "Get the late products.", {}, [], retries=2)
N["fetch_account"] = {"name": "fetch_account", "node_type": "api_request", "passthrough": True, "passthrough_default_transition": "account",
                      "on_enter": {"type": "silent"}, "pre_actions": [fetch],
                      "response_mapping": [{"path": "data.products", "variable": "products"}],
                      "transitions": [{"target_node": "account", "description": "always", "condition": {"operator": "always"}}]}
N["account"] = code_node("account", ACCOUNT_CODE, "collect")

N["collect"] = {
    "name": "collect", "node_type": "conversation", "on_enter": {"type": "tts", "text": "{{debt_statement}}"}, "on_enter_first_entry_only": True,
    "task_message": COLLECT_TASK,
    "tools": [api_tool("create_promise", "Record one payment promise for one product. CALL it only after the customer said a clear yes to the full read-back, once per agreed product.",
                       {"product_id": {"type": "string", "default": "{{product_id}}", "description": "product_id from the account facts"},
                        "amount": {"type": "number", "default": "{{amount}}", "description": "Agreed amount, a number, from the floor up to the full past-due amount."},
                        "date": {"type": "string", "default": "{{date}}", "description": "Agreed date YYYY-MM-DD, a business day, today or later, not after the product's deadline."}},
                       ["product_id", "amount", "date"], retries=0, post=PROMISE_POST),
              api_tool("add_note", "Record why one product ended without a promise. CALL it once per product without a recorded promise, after the promises are recorded. NEVER call it when a transfer happened or will happen.",
                       {"product_id": {"type": "string", "default": "{{product_id}}", "description": "product_id from the account facts"},
                        "reason": {"type": "string", "enum": ["refused", "hardship", "dispute", "paid", "service_error"], "default": "{{note_reason}}", "description": "refused: attempts used up or refuses to talk; hardship: hardship and declined support; dispute: not mine / never had it / closed; paid: already paid this amount; service_error: create_promise failed twice."}},
                       ["product_id", "reason"], retries=0, post=NOTE_POST),
              transfer_tool(["restructuring", "general", "support"], "Hand the call to a person. CALL it for a new payment plan or lower instalments (restructuring), a customer who insists on a human after one offer of help (general), or hardship when the customer accepts support (support)."),
              close_tool(["promise", "paid", "transferred", "no_promise"], ["refused", "hardship", "dispute", "service_error", "restructuring", "human", "support"],
                         "promise: at least one promise recorded (no transfer). paid: no promise and every product noted paid. transferred + restructuring/human/support: after a transfer. no_promise + the reason of the first product (account order) whose note is not paid.")],
    "transitions": [END_T],
}

N["end"] = {"name": "end", "node_type": "end_call", "on_enter": {"type": "silent"}, "disable_inactivity_monitor": True, "transitions": [],
            "terminal": {"type": "function", "function": {"name": "call_closed", "handler": "__function__:end_call",
                         "parameters": {"type": "object", "properties": {"message_mode": {"type": "string", "default": "none"}}}}}}

with open("out/brief-b.workflow.json", "w", encoding="utf-8") as f:
    json.dump(WF, f, indent=1, ensure_ascii=False)
print("written")
