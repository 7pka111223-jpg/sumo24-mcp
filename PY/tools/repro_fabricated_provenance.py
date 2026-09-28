"""repro_fabricated_provenance.py — final review finding H1.

A coefficient whose magnitude is pure invention passes rung 1 (lint), accept()
and may_emit() with ZERO flags, as long as it carries a self-asserted strong
provenance string ("user-measured"). Nothing verifies a source, nothing checks
the value, and weak-provenance reporting never fires because the provenance
enum value is STRONG by declaration, not by evidence.

Exit 0 = defect reproduced (broken). Exit 1 = fixed (the guards fire).
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "PY"))
import spec_review as sr  # noqa: E402

spec = {
    "identity": {"name": "adversarial", "version": "v1"},
    "parameters": [
        # fabricated magnitude, self-asserted strong provenance, no source
        {"symbol": "mu_fab", "name": "fabricated growth rate",
         "value": 0.5, "provenance": "user-measured"},
        # prose variants that the keyword filter misses
        {"symbol": "p_tilde", "name": "tilde prose",
         "value": "~0.5", "provenance": "user-measured"},
        {"symbol": "p_paren", "name": "parenthesised prose",
         "value": "0.5 (typical)", "provenance": "user-measured"},
    ],
}

v = sr.lint(spec)
strong_passes = v["ok"] and not v["weak_provenance"] and not v["unparseable"]
tilde_caught = any(u["value"] == "~0.5" for u in v["unparseable"])
paren_caught = any(u["value"] == "0.5 (typical)" for u in v["unparseable"])

a = sr.accept(spec, "adversarial-review")
e = sr.may_emit(spec)

print(f"fabricated strong-provenance value passes lint : {strong_passes}")
print(f"  lint errors                                  : {v['errors']}")
print(f"  weak_provenance flagged                      : {len(v['weak_provenance'])}")
print(f"'~0.5' caught by prose filter                  : {tilde_caught}")
print(f"'0.5 (typical)' caught by prose filter         : {paren_caught}")
print(f"accept() accepts the fabricated spec           : {a['accepted']}")
print(f"may_emit() allows the fabricated spec          : {e['may_emit']}")

if strong_passes and a["accepted"] and e["may_emit"]:
    print("RESULT: REPRODUCED - fabricated magnitude reaches emission with zero flags")
    sys.exit(0)
print("RESULT: FIXED")
sys.exit(1)
