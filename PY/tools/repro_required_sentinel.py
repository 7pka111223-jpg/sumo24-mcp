"""Reproducer: the REQUIRED sentinel - the project's core fabrication guardrail - is
enforced by NOBODY.

Map Q5 makes REQUIRED a first-class unfilled-value sentinel. The schema documents it as
"a coefficient whose 'value' equals this fails the linter until replaced". Ticket 05's answer
states plainly that JSON Schema cannot enforce it (the field must also accept symbolic
expressions), so "enforcing REQUIRED is a rung-1 LINTER duty".

There is no linter module in the tree.

This script plants an unfilled REQUIRED into a shipped fixture and runs every gate that exists:
  1. JSON Schema validation  -> PASSES (by design; the sentinel is a legal value)
  2. dimension_checker       -> ok=True
  3. continuity_checker      -> verdict is BYTE-IDENTICAL to the clean spec

(3) is the dangerous part. continuity_checker does recognise the literal "REQUIRED" and marks
the term unresolved - but a Type B spec ALWAYS carries unresolved inherited model-base symbols,
so an unfilled REQUIRED is indistinguishable from routine deferral. The signal is masked.

Net: a spec with an unfilled placeholder coefficient passes rung 1.5 clean and produces exactly
the same rung-2 report as a complete one. Nothing stops it reaching a simulation.
"""
import copy, json, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import jsonschema
import continuity_checker as cc
import dimension_checker as dc
import spec_review as sr

HERE = pathlib.Path(__file__).resolve().parents[1]
FIXTURE = HERE / "data/fixtures/unit_spec_typeB_sulfideoxidation_v1.json"
SCHEMA = HERE / "data/unit_spec.schema.json"
BASE = r"D:/SUMO24/Process code/Model base/Focus models/Sumo2C.xlsm"

def main() -> int:
    clean = json.loads(FIXTURE.read_text(encoding="utf-8"))
    dirty = copy.deepcopy(clean)
    dirty["processes"][0]["stoichiometry"][0]["coefficient"]["value"] = "REQUIRED"

    v = jsonschema.Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))
    schema_ok = not list(v.iter_errors(dirty))
    dim = dc.check_spec(dirty)
    c_clean = cc.check_spec(clean, BASE)
    c_dirty = cc.check_spec(dirty, BASE)
    identical = json.dumps(c_clean.get("processes")) == json.dumps(c_dirty.get("processes"))

    print("1. schema validation      :", "PASSES" if schema_ok else "fails")
    print("2. dimensional rung (1.5) :", "PASSES (ok=%s)" % dim.get("ok"))
    print("3. continuity rung (2)    : clean ok=%s / REQUIRED ok=%s%s"
          % (c_clean.get("ok"), c_dirty.get("ok"),
             "  -> VERDICTS IDENTICAL" if identical else "  -> differs"))
    rung1 = sr.lint(dirty)
    rung1_clean = sr.lint(clean)
    gate = sr.may_emit(dirty)
    print("4. rung 1 (spec_review)   : ok=%s, %d REQUIRED named%s"
          % (rung1["ok"], len(rung1["required"]),
             "" if not rung1["required"] else " -> " + rung1["required"][0]["what"]))
    print("5. emission gate          :", "REFUSES" if not gate["may_emit"] else "ALLOWS",
          "-", gate["reason"])
    # Rung 1 must catch the planted sentinel AND distinguish it from the clean spec,
    # so a linter that simply fails everything would not pass this test.
    caught = (not rung1["ok"]
              and len(rung1["required"]) > len(rung1_clean["required"])
              and not gate["may_emit"])
    print("")
    print("RESULT:", "FIXED - rung 1 catches the unfilled sentinel and the gate refuses"
          if caught else "REPRODUCED - no gate catches an unfilled REQUIRED")
    return 0 if caught else 1

if __name__ == "__main__":
    sys.exit(main())
