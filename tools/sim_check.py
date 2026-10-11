"""Run a few hand-written customers against a phone agent and print each conversation (spends a little credit).

    python tools/sim_check.py <agent_id> <personas.json>

personas.json: [{"name": "...", "prompt": "who the customer is and what they want", "success": "what must happen",
                 "variables": {"customerNumber": "...", "now": "..."}}, ...]
"""
import json, pathlib, sys, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import freya

def main(agent_id, path):
    cases = json.load(open(path, encoding="utf-8"))
    made = freya.create_personas([{"name": c["name"] + time.strftime(" %H%M%S"), "prompt": c["prompt"], "successCriteria": c["success"], "tags": ["check"]} for c in cases])["personas"]
    ids = {p["id"]: c for p, c in zip(made, cases)}
    print(f"running {len(cases)} customers ...", flush=True)
    sim_id, it_id, status = freya.run_simulation(agent_id, "check " + time.strftime("%H:%M:%S"), {pid: c["variables"] for pid, c in ids.items()}, max_seconds=300)
    for r in freya.get_iteration(sim_id, it_id)["runs"]:
        c = ids.get(r.get("personaId"), {"name": "?"})
        print("\n" + "=" * 70 + f"\n{c['name']}: {str(r.get('outcome')).upper()}  {' '.join(str(r.get('reason') or '').split())[:300]}")
        if not r.get("callId"): continue
        call = freya.get_call(r["callId"])
        print("ended:", call.get("endedReason"))
        for m in call.get("messages", []):
            role, text = m.get("role"), str(m.get("message") or m.get("content") or "")
            if role in ("user", "assistant", "bot") and text.strip():
                print(f"  {role[:4]}: {' '.join(text.split())[:400]}")
            elif "function_call" in text or role in ("tool", "function"):
                print(f"  [{role}] {' '.join(text.split())[:160]}")
    print(f"\nsimulation {sim_id}, status {status}")

if __name__ == "__main__":
    if len(sys.argv) != 3: sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
