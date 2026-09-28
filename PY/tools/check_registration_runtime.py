"""Runtime registration check — what the server ACTUALLY registers, not what the source looks like.

`check_dispatch_coverage.py` reads `server.py` statically. That was sufficient while every tool
was a literal `types.Tool(name="...")`. Group HH registers dynamically from
`hh_tools.TOOL_DEFS` — one source of truth instead of 24 duplicated literals — so the static
reader is blind to it and reports 211.

Rather than duplicate the definitions into `server.py` to keep a static reader happy, this
verifier IMPORTS the server and calls `list_tools()`. It checks what the running server exposes,
which is the thing that actually matters:

  * the total count,
  * that EVERY one of the pre-existing names is still present (set comparison, not a count —
    a count alone passes if an edit silently REPLACES a tool),
  * that every hh_ tool is reachable through the dispatcher,
  * that no name is duplicated.

Usage:  python PY/tools/check_registration_runtime.py [baseline.json]
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
PY = HERE.parent
sys.path.insert(0, str(PY))
sys.path.insert(0, str(PY.parent))


def main(argv: list[str]) -> int:
    try:
        import server
    except Exception as e:
        print(f"FAIL: could not import server.py: {type(e).__name__}: {e}")
        return 1

    try:
        tools = asyncio.run(server.list_tools())
    except Exception as e:
        print(f"FAIL: list_tools() raised: {type(e).__name__}: {e}")
        return 1

    names = [t.name for t in tools]
    uniq = sorted(set(names))
    hh = sorted(n for n in names if n.startswith("hh_"))
    print(f"registered at runtime : {len(names)}  (unique {len(uniq)})")
    print(f"Group HH tools        : {len(hh)}")

    ok = True
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        print(f"FAIL duplicate names  : {dupes}")
        ok = False

    baseline_path = argv[1] if len(argv) > 1 else None
    if baseline_path and pathlib.Path(baseline_path).exists():
        before = set(json.loads(pathlib.Path(baseline_path).read_text(encoding="utf-8")))
        missing = sorted(before - set(names))
        print(f"baseline names        : {len(before)}")
        if missing:
            print(f"FAIL lost from baseline: {missing[:10]}")
            ok = False
        else:
            print("baseline preserved    : all present (set comparison, not a count)")
        added = sorted(set(names) - before)
        print(f"newly added           : {len(added)}")

    # every hh_ tool must be reachable through the dispatcher
    try:
        import hh_tools
        defined = set(hh_tools.TOOL_NAMES)
        unreachable = sorted(defined - set(names))
        stray = sorted(set(hh) - defined)
        if unreachable:
            print(f"FAIL defined but not registered: {unreachable}")
            ok = False
        if stray:
            print(f"FAIL registered but not defined: {stray}")
            ok = False
        if not unreachable and not stray:
            print(f"hh_ definitions match : {len(defined)} defined == {len(hh)} registered")
        bad = [n for n in defined
               if hh_tools.dispatch(n, {}).get("error", "").startswith("unknown Group HH tool")]
        if bad:
            print(f"FAIL not routed by dispatch: {bad}")
            ok = False
        else:
            print("dispatch routing      : every hh_ tool is routed")
    except Exception as e:
        print(f"FAIL hh_tools check: {type(e).__name__}: {e}")
        ok = False

    print("\nRESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
