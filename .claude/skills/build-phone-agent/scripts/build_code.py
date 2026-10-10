"""Build the Python source of a Freya code node and test it locally, before any simulation.

    python build_code.py SNIPPET.py                      # check it, print the source size
    python build_code.py SNIPPET.py --out code.txt        # write the full source (calendar_lib + snippet)
    python build_code.py SNIPPET.py --run vars.json       # run it on a fake `vars` and print what it wrote

SNIPPET.py is code you write for one code node. It runs after calendar_lib.py, so it can use
Calendar, parse_now, spoken, read_list and money. It reads and writes the dict `vars`.

The full source is what goes into the node's code_exec `code` default. Put it into the workflow
JSON with json.dumps, never by hand. The checks here catch what fails silently on the platform:
a doubled brace, a syntax error, an exception, or a variable a prompt needs that was not written.
"""
import argparse, json, pathlib, sys, traceback

HERE = pathlib.Path(__file__).resolve().parent
LIB = (HERE / "calendar_lib.py").read_text(encoding="utf-8")


def build(snippet_text):
    src = LIB + "\n\n# ---- snippet ----\n" + snippet_text
    problems = []
    for bad in ("{" * 2, "}" * 2):
        if bad in src:
            line = next(i + 1 for i, l in enumerate(src.splitlines()) if bad in l)
            problems.append("doubled brace %r at source line %d: Freya may treat it as a placeholder. "
                            "Split nested literals, e.g. build the inner dict first." % (bad, line))
    try:
        compile(src, "code_node", "exec")
    except SyntaxError as e:
        problems.append("syntax error: %s (line %s)" % (e.msg, e.lineno))
    return src, problems


def run(src, variables):
    env = {"vars": dict(variables)}
    before = set(env["vars"])
    exec(compile(src, "code_node", "exec"), env)
    v = env["vars"]
    return {k: v[k] for k in v if k not in before or v[k] != variables.get(k)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("snippet")
    ap.add_argument("--out")
    ap.add_argument("--run", help="JSON file with the variables the node will see (call variables, earlier results)")
    ap.add_argument("--expect", nargs="*", default=[], help="variable names that must be written and non-empty")
    a = ap.parse_args()
    src, problems = build(pathlib.Path(a.snippet).read_text(encoding="utf-8"))
    for p in problems:
        print("PROBLEM:", p)
    if problems:
        sys.exit(1)
    print("ok: %d characters" % len(src))
    if a.out:
        pathlib.Path(a.out).write_text(src, encoding="utf-8")
        print("wrote", a.out)
    if a.run:
        variables = json.loads(pathlib.Path(a.run).read_text(encoding="utf-8"))
        try:
            written = run(src, variables)
        except Exception:
            traceback.print_exc()
            print("PROBLEM: the snippet raised. On the platform this leaves its variables unset. Wrap it in try/except.")
            sys.exit(1)
        for k, v in written.items():
            print("--- %s ---" % k)
            print(v)
        missing = [n for n in a.expect if not str(written.get(n, "")).strip()]
        if missing:
            print("PROBLEM: not written or empty:", ", ".join(missing))
            sys.exit(1)


if __name__ == "__main__":
    main()
