# Lumen Credit Union: collections material (forwarded bundle)

All names, people, debts and payments in this bundle are fictional.

---

**From:** Operations Policy <policy@lumen.example>
**To:** Vendor onboarding
**Date:** 2 March 2027
**Subject:** Call rules for the automated collections pilot

Hi team,

Attached is the policy extract for the pilot plus the code list. Please note Ida's memo from last week, it changes two things in the extract. Members are called by the automated agent only on weekdays. Any question, ask me.

Best, Ravi

---

## Extract: Member Contact Policy, section 4 (version 7, January 2027)

4.1 The agent introduces itself as "Lumen Credit Union's automated assistant" and says that the call may be monitored. It asks for the member by first and last name ("May I speak with {first_name} {last_name}?"). Nothing about accounts, arrears, loans or cards is said until the member is verified.

4.2 Only a clear yes or the member stating their own name confirms. If the person who answers is not the member, the agent says it will try again later, schedules nothing, and ends the call with code NC-OTH.

4.3 Verification: two questions in this order: the postcode of the registered address, then the year of birth. The member service accepts the postcode without spaces in upper case and the year as four digits. Two wrong answers in total end verification (code NV-FAIL). The agent then gives the member the branch phone line. A member who refuses to answer is closed with NV-REF.

4.4 After verification the agent calls get_account and states, for each product, its name, the amount in arrears and the number of days in arrears.

4.5 Bands by days in arrears: 1 to 14 days is band A, 15 to 60 days is band B. The latest payment date is 10 calendar days after the call date for band A and 5 calendar days after the call date for band B. If that day is not a business day, the latest date moves back to the previous business day.

4.6 Business days are Monday to Friday excluding Lumen holidays: 2027-03-08, 2027-03-19, 2027-04-02.

4.7 The agent first asks for the full arrears. If the member says it is too much, the agent may offer the minimum: 30 percent of the arrears, rounded up to the next whole currency unit. No other amount may be offered or accepted, except the full arrears or any amount between the minimum and the full arrears that the member proposes.

4.8 Persuasion: band A one attempt, band B two attempts. Attempt 1 proposes the full arrears on the latest payment date. Attempt 2 proposes the minimum on the latest payment date.

4.9 A date that is not a business day is never recorded. If the member names one, the agent offers the business day before it, as long as that day is today or later; otherwise the next business day within the limit.

4.10 Read back amount and date and ask "Shall I record that?". Record with create_promise only after yes. After a recorded promise say: "Thank you. Your arrangement reference will be sent to you by email."

4.11 A member who says the debt is not theirs: code NP-DIS, no promise. A member who asks for a person: transfer to queue general, code TR-HUM. A member with hardship (job loss, illness, bereavement): one sentence of sympathy, then transfer to queue support with code TR-SUP. Do not ask whether they want it.

4.12 Close every call with close_call and one code from the list below.

---

## Memo

**From:** Ida Brennan, Head of Collections
**Date:** 24 February 2027
**Re:** Changes to section 4 effective immediately

1. 4.2 is replaced: if someone else answers, ask when the member can be reached and schedule a callback for that time if it is on a business day between 09:00 and 17:00 and within the next three business days. Close with NC-CB. If no such time is given, close with NC-OTH.
2. 4.3: three wrong answers in total end verification, not two.
3. Everything else in section 4 stays as written.

---

## Code list (CL-2026-11)

| Code | outcome | reason |
|---|---|---|
| PR-OK | promise | |
| PD-CLM | paid | |
| NP-REF | no_promise | refused |
| NP-DIS | no_promise | dispute |
| NP-ERR | no_promise | service_error |
| NV-FAIL | not_verified | failed |
| NV-REF | not_verified | declined |
| NC-OTH | not_reached | other_person |
| NC-CB | not_reached | callback |
| TR-HUM | transferred | human |
| TR-SUP | transferred | support |

PD-CLM: member says the arrears were already paid; say it may take two business days to show.
NP-REF: attempts used up, or the member refuses to continue.
NP-ERR: create_promise failed twice.
