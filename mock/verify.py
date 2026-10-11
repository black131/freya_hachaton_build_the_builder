import json, sys, urllib.request, time
B = sys.argv[1].rstrip("/") + "/voice/v1/"
D = json.load(open(sys.argv[2]))
def parse(status, raw):
    try: return status, json.loads(raw)
    except Exception: return status, {"_not_json": raw[:300].decode("utf-8", "replace")}
def post(svc, data):
    req = urllib.request.Request(B + svc, json.dumps({"data": data, "call": {"ani": "5000000000", "lang": "tr"}}).encode(),
                                 {"content-type": "application/json", "user-agent": "Mozilla/5.0 (verify)", "accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r: return parse(r.status, r.read())
    except urllib.error.HTTPError as e: return parse(e.code, e.read())
ok = bad = 0
def check(svc, data, entry):
    global ok, bad
    s, body = post(svc, data)
    if s == entry["http"] and body == entry["response"]: ok += 1
    else:
        bad += 1; print("MISMATCH", svc, data, "got", s, "want", entry["http"], str(body)[:200])
        if bad >= 5: print("stopping after 5 mismatches"); sys.exit(1)
for c in D["customers"]:
    no = c["customerNo"]
    for svc, t in c["services"].items():
        if "http" in t:
            base = {"customerNo": int(no) if svc == "contact.email.get" else no}
            if svc == "cards.list": base["aiFlow"] = "CardOps"
            if svc == "contact.email.get": base["intAddressInfoType"] = "E"
            if svc == "statement.pdf.send": base.update(cardNumber="x", currencyType="TL", statementDate="05.10.2026", emailAddress="a@b.c")
            if t.get("delaySeconds"): print("delay entry", no, svc)
            check(svc, base, t); continue
        for card, e in t.items():
            if "http" in e: check(svc, {"cardNumber": card}, e); continue
            for wk, e2 in e.items(): check(svc, {"cardNumber": card, "newStatementWeek": int(wk), "statementDay": 5}, e2)
print("exact matches:", ok, "mismatches:", bad)
for svc, data in [("cards.list", {"customerNo": "11111111"}), ("cards.balance", {"cardNumber": "5400********1234"}), ("statement.week.get", {"cardNumber": "999999******0000"}),
                  ("statement.week.decide", {"cardNumber": "540000******1234", "newStatementWeek": 1}), ("contact.email.get", {"customerNo": "11111111", "intAddressInfoType": "E"}),
                  ("cards.balance", {"cardNumber": ""}), ("contact.email.get", {"customerNo": "90000001"}), ("cards.list", {"customerNo": "{{customerNumber}}"})]:
    s, b = post(svc, data); print(svc, data, "->", s, (b.get("result") or {}).get("code"), (b.get("result") or {}).get("message"))
