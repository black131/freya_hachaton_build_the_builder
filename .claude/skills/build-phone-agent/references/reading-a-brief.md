# Reading a brief into a spec

Most failed customers come from one rule that was skipped. Before you write any workflow, turn
the brief into `out/<slot>.spec.md`: a numbered list of every rule, each with where it will be
enforced. The workflow is then written from the spec, and the spec is checked against the brief.

## When the brief is raw material

A brief can arrive as a clean specification or as a bundle: a mail, a policy extract, a memo that
changes the policy, a code list. Then:

1. Read every document fully once before writing anything.
2. Note each document's date and author. A later memo or mail that says it replaces, changes or
   adds a rule wins over the policy for that rule only. Everything it does not mention stays.
3. Code lists (outcome codes, reason codes, queue names, product codes) are the values the tools
   accept. Cross-check them with the enums in the tool API file. If the two disagree, the tool API
   file decides what the bank accepts; the brief decides when to use it. Write the conflict down.
4. Look for rules hidden in prose: examples, footnotes, "note that", "except", "unless", table
   captions, a sentence in a mail signature block.
5. Write a section "Changes applied" in the spec: which document changed which rule.

## What to extract

Go through this list for every brief. Each item is a question; the answer comes only from the
brief and its tool API file. If the brief is silent, write "not specified" and use the most
conservative behaviour.

**Call inputs**: which call variables exist and what each means; how to address the customer.

**Opening**: the exact first sentence and its required parts; what may not be said before
verification (forbidden words, product names, the reason for the call); the confirmation question.

**Who is on the line**: what counts as confirmation and what does not; how many times to ask;
what closes the call if it stays unclear; relative or other person; wrong number; deceased; what a
third party may and may not be told; callback rules (which days, hours, inclusive limits, relative
to `now`), and what to do when the offered time is outside the window.

**Identity**: the questions, their order, the exact format each answer is sent in (dates, digit
counts), how to read ambiguous spoken formats, how many wrong answers end the check and whether
they count per question or in total, special hints from the API and what they change, what to say
after failure, refusal to answer and how many refusals close the call.

**Stating the debt**: when (after which tool result), what to say, how to name each product, which
figures to include, the order of several products.

**Calendar**: business days, weekend, holidays, any time-of-day cut-off, how "next <weekday>",
"this <weekday>", vague periods and weekends are interpreted.

**Limits per product**: the band table (by days late or by amount or by product type), the
deadline per band and exactly how it is counted (business or calendar days, today included or
not), the floor amount per product type, the number of persuasion attempts, what each attempt
offers (amount and date).

**Negotiation**: the first question; what counts as a refusal and what does not; what a proposed
date or amount triggers; amount above the floor, below the floor, above the full amount; changes
at the read-back; forbidden offers and forbidden questions; when to stop.

**Special situations**, with their priority over persuasion: hardship (which words), already paid,
dispute (and how it differs from already paid), restructuring, human request, scam question,
robot question, unanswerable questions, not wanting to talk, a promise followed by a transfer.

**Recording**: read-back content and the confirmation question; tool call order; one or many
promises per product; retry rule on failure; sentence after a recorded promise; what may not be
changed after recording.

**Several products** (when the brief allows them): order, one ask for all first or not, attempts
per product, one date for all versus per-product deadlines, notes for products without a promise,
what a dispute or a transfer on one product does to the others.

**Closing**: the outcome table (outcome, reason, when), its priority rules when several apply,
what must be said before closing, that `close_call` is the last tool call.

**Tool API**: for each tool, its URL, body fields, required fields, enums, response fields
(including hints and error values). Note every enum value; the agent's tool fields must use the
same enums.

## Spec format

```markdown
# Spec: <slot>
Sources: <files>, Changes applied: <memo X replaces rule Y>

## Values
Holidays: ...  Weekend: ...  Bands: ...  Floors: ...  Outcome table: ...

## Rules
1. <rule in one line> | where: setup code / greet prompt / identity post-hook / collect prompt / close_call enum / transition
2. ...

## Required sentences (verbatim)
- "<sentence>" | when: ...

## Forbidden before verification
- words: ...  topics: ...
```

Then check: is every numbered rule of the brief in the list? Count them if the brief numbers them.
Is every rule mapped to a place in the workflow? A rule with no place is a rule the agent will not
follow.
