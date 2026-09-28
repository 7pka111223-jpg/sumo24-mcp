"""Reproducer: the substance-basis crossing guard in PY/dimension_checker.py is inert.

Ticket 20 states the crossing surface is "implemented and unit-tested, and will fire for a
corrected spec". It does not. This spec has NO model-expandable symbols, a fully resolvable
COD-denominated rate (mu * XB, XB in g COD.m-3) and an S-denominated component (SS in
g S.m-3) whose yield Y is declared g COD.g COD-1 - i.e. the g S <-> g COD conversion is
absent. That is a genuine undeclared substance-basis crossing.

Expected: substance_crossings names it.
Actual:   substance_crossings == [] and both rows report dimension-ok.

Why it matters: g S and g COD are both M.L^-3, so the pure dimensional check CANNOT catch
this - the substance-qualifier layer is the only guard, and it is the guard for exactly the
silent-failure class Type B was accepted for (map Q14, "with teeth").
"""
import json, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import dimension_checker as dc

SPEC = {
    "schema_version": "1.0.0",
    "parameters": [
        {"symbol": "mu", "name": "rate", "unit": "d-1",
         "value": {"value": 1, "provenance": "user-stated", "source": "repro"}},
        {"symbol": "Y", "name": "yield", "unit": "g COD.g COD-1",
         "value": {"value": 0.1, "provenance": "user-stated", "source": "repro"}}],
    "state_variables": {"introduced": [
        {"symbol": "XB", "name": "biomass", "unit": "g COD.m-3", "handling": "Integrated"},
        {"symbol": "SS", "name": "sulfide", "unit": "g S.m-3", "handling": "Integrated"}],
        "referenced": []},
    "processes": [{"id": "r1", "name": "growth", "rate_expression": "mu * XB",
                   "stoichiometry": [
                       {"component": "SS", "coefficient": {"value": "-1/Y"}},
                       {"component": "XB", "coefficient": {"value": "1"}}]}],
    "code_blocks": []}

def _demo() -> int:
    r = dc.check_spec(SPEC)
    p0 = r["processes"][0]
    crossings = r.get("substance_crossings")
    print("process verdict     :", p0.get("verdict"))
    print("row verdicts        :", [(s["component"], s["verdict"]) for s in p0["stoichiometry"]])
    print("substance_crossings :", json.dumps(crossings))
    ok = bool(crossings)
    print("\nRESULT:", "FIXED - crossing detected" if ok else
          "REPRODUCED - crossing NOT detected (guard is inert)")
    sys.exit(0 if ok else 1)


# --------------------------------------------------------------------------- #
# Regression guard added after the fix (2026-09-06).
# A crossing detector is only useful if it fires on real crossings AND stays quiet
# when the conversion IS declared. Both directions are checked here, plus the case a
# naive "does the rate mention it" test misses.
# --------------------------------------------------------------------------- #

def _fixture(path):
    import json, pathlib
    return json.loads((pathlib.Path(__file__).resolve().parents[1] / path).read_text(encoding="utf-8"))


def regression() -> int:
    import copy
    ok = True

    # 1. declared conversion (Y_SOB = g XSOB.g S-1) -> must be QUIET
    good = _fixture("data/fixtures/unit_spec_typeB_sulfideoxidation_v1.json")
    q = dc.check_spec(good).get("substance_crossings")
    print(f"  declared conversion -> quiet          : {not q}")
    ok &= not q

    # 2. conversion removed (Y_SOB = g COD.g COD-1) -> must FIRE.
    #    This is the case a "does the rate mention that basis" test misses, because the
    #    rate's Monod term mentions SH2S while establishing no conversion at all.
    broken = copy.deepcopy(good)
    for p in broken["parameters"]:
        if p["symbol"] == "Y_SOB":
            p["unit"] = "g COD.g COD-1"
    b = dc.check_spec(broken).get("substance_crossings")
    print(f"  conversion removed  -> fires          : {bool(b)}")
    ok &= bool(b)

    # 3. Type A (no new state variables, no crossings) -> quiet
    a = dc.check_spec(_fixture("data/fixtures/unit_spec_typeA_equalization_v1.json"))
    print(f"  Type A fixture      -> quiet          : {not a.get('substance_crossings')}")
    ok &= not a.get("substance_crossings")
    return 0 if ok else 1


def _mk(params, svs, procs, code_blocks=None):
    return {"schema_version": "1.0.0", "parameters": params,
            "state_variables": {"introduced": svs, "referenced": []},
            "processes": procs, "code_blocks": code_blocks or []}


# Reviewer-added cases (second-pass review, 2026-09-06): the coefficient-centred rule
# has known false negatives and a false-positive edge. Expected outcomes are the CURRENT
# behaviour; where it is wrong the case documents the residual hole instead of failing.
def regression_review() -> int:
    import copy
    print("  (expected-current values in parens; HOLE = the rule cannot see it)")
    r = {}

    # R1. Monod-mention false negative: rate COD-denominated via XB, Monod term merely
    #     MENTIONS SS (g S) — establishes no conversion — and the coefficient is a bare
    #     number, so the rule falls back to the rate basis and the mention masks the hole.
    r["R1 Monod-mention + bare coeff (HOLE: quiet)"] = bool(dc.check_spec(_mk(
        [{"symbol": "mu", "unit": "d-1", "value": {"value": 1, "provenance": "user-stated"}},
         {"symbol": "KH", "unit": "g S.m-3", "value": {"value": 0.5, "provenance": "user-stated"}}],
        [{"symbol": "XB", "unit": "g COD.m-3", "handling": "Integrated"},
         {"symbol": "SS", "unit": "g S.m-3", "handling": "Integrated"}],
        [{"id": "r1", "rate_expression": "mu * (SS / (KH + SS)) * XB", "stoichiometry": [
            {"component": "XB", "coefficient": {"value": "1"}},
            {"component": "SS", "coefficient": {"value": -1.5}}]}])
        ).get("substance_crossings"))

    # R2. wrong-basis coefficient: Y in g S.g S-1 carries S, so the rule is quiet, but
    #     the rate is COD-denominated and no COD->S conversion exists.
    r["R2 wrong-basis coeff (HOLE: quiet)"] = bool(dc.check_spec(_mk(
        [{"symbol": "mu", "unit": "d-1", "value": {"value": 1, "provenance": "user-stated"}},
         {"symbol": "Y", "unit": "g S.g S-1", "value": {"value": 0.1, "provenance": "user-stated"}}],
        [{"symbol": "XB", "unit": "g COD.m-3", "handling": "Integrated"},
         {"symbol": "SS", "unit": "g S.m-3", "handling": "Integrated"}],
        [{"id": "r1", "rate_expression": "mu * XB", "stoichiometry": [
            {"component": "SS", "coefficient": {"value": "1/Y"}},
            {"component": "XB", "coefficient": {"value": "1"}}]}])
        ).get("substance_crossings"))

    # R3. conversion declared only in code_blocks (iCODS = g COD.g S-1) with a numeric
    #     coefficient that never references it: the rule fires (arguably correct — a bare
    #     numeric conversion is an untraceable magnitude — but it cannot see the declaration).
    r["R3 conversion declared in code, coeff bare (fires)"] = bool(dc.check_spec(_mk(
        [{"symbol": "mu", "unit": "d-1", "value": {"value": 1, "provenance": "user-stated"}}],
        [{"symbol": "XB", "unit": "g COD.m-3", "handling": "Integrated"},
         {"symbol": "SS", "unit": "g S.m-3", "handling": "Integrated"}],
        [{"id": "r1", "rate_expression": "mu * XB", "stoichiometry": [
            {"component": "SS", "coefficient": {"value": -1.9958}},
            {"component": "XB", "coefficient": {"value": "1"}}]}],
        code_blocks=[{"section": "constants", "lines": [
            {"symbol": "iCODS", "expression": "1.9958", "unit": "g COD.g S-1"}]}])
        ).get("substance_crossings"))

    # R4. explicit COD rate_unit, S component, bare numeric coefficient -> must FIRE.
    r["R4 explicit COD rate_unit, bare coeff (must fire)"] = bool(dc.check_spec(_mk(
        [{"symbol": "mu", "unit": "d-1", "value": {"value": 1, "provenance": "user-stated"}}],
        [{"symbol": "XB", "unit": "g COD.m-3", "handling": "Integrated"},
         {"symbol": "SS", "unit": "g S.m-3", "handling": "Integrated"}],
        [{"id": "r1", "rate_expression": "mu * XB", "rate_unit": "g COD.m-3.d-1",
          "stoichiometry": [
            {"component": "SS", "coefficient": {"value": -1.5}},
            {"component": "XB", "coefficient": {"value": "1"}}]}])
        ).get("substance_crossings"))

    ok = True
    expect = {"R1 Monod-mention + bare coeff (HOLE: quiet)": False,
              "R2 wrong-basis coeff (HOLE: quiet)": False,
              "R3 conversion declared in code, coeff bare (fires)": True,
              "R4 explicit COD rate_unit, bare coeff (must fire)": True}
    for name, got in r.items():
        want = expect[name]
        good_now = (got == want)
        ok &= good_now
        print(f"  {name:52s} -> {'fires' if got else 'quiet'}  "
              f"{'as-expected' if good_now else 'UNEXPECTED'}")
    print("  R1/R2 are the residual false negatives the coefficient-centred rule keeps.")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--regression" in sys.argv:
        print("substance-crossing regression:")
        sys.exit(regression())
    if "--regression-review" in sys.argv:
        print("substance-crossing regression (reviewer-added cases):")
        sys.exit(regression_review())
    sys.exit(_demo())
