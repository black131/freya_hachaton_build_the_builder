"""Read the result of a simulation that already ran, without starting a new one (no credit spent).

    python tools/read_simulation.py <simulation_id>

Use it when run_cases.py crashed on a platform error while the simulation went on running on Freya.
It waits until the simulation is finished, then prints, for each call: the case, the judge's verdict,
the bank tools the agent called, and the judge's reason when it failed. The bank-ledger part of
run_cases.py's score is not repeated here; the tool order shows most of it.
"""
import json, pathlib, re, sys, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import freya

BANK = ("verify_identity", "get_account", "create_promise", "add_note", "schedule_callback", "transfer_to_agent", "close_call")

def main(sim_id):
    while True:
        s = freya.api("GET", f"/api/v2/simulations/{sim_id}"); s = s.get("simulation") or s
        if s.get("status") in ("completed", "failed", "paused"): break
        print("status:", s.get("status"), "- waiting 20 s", flush=True); time.sleep(20)
    its = freya.api("GET", f"/api/v2/simulations/{sim_id}/iterations"); its = its.get("iterations") or its.get("items") or its
    runs = freya.get_iteration(sim_id, its[0]["id"])["runs"]
    passed = 0
    for r in runs:
        name = r.get("personaName") or (r.get("persona") or {}).get("name") or r.get("personaId")
        tools = []
        if r.get("callId"):
            for m in freya.get_call(r["callId"]).get("messages", []):
                hit = re.search(r'"function_call_start".{0,40}?"function"\s*:\s*"(\w+)"', str(m.get("message", "")).replace('\\"', '"'))
                if hit and hit.group(1) in BANK: tools.append(hit.group(1).replace("verify_identity", "verify").replace("create_promise", "promise"))
        ok = r.get("outcome") == "pass"; passed += ok
        print(("PASS" if ok else "FAIL"), str(name)[:40], "|", " > ".join(tools) or "(no bank tool calls)")
        if not ok: print("       -", " ".join(str(r.get("reason") or "no verdict").split())[:300])
    print(f"\n{passed} / {len(runs)} passed by the judge (simulation {sim_id}, status {s.get('status')}).")

if __name__ == "__main__":
    if len(sys.argv) != 2: sys.exit(__doc__)
    main(sys.argv[1])
