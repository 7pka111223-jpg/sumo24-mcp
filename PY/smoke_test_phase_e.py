"""Gate E — acceptance test for ticket 12 Phase E (rung 5).

Rung 5 is the runtime rung: 5a conservative tracer, 5b degenerate equivalence. 5b had been
UNEXERCISED for the whole project — first because reactive units would not compile (tickets
21-23, wrong premise), then because the `-nosort` build's algebraic layer never evaluated.

  A. static guards      — DTT-absent and model-missing paths return refusals, not crashes
  B. the sentinel guard — a `-nosort` build MUST be refused, not measured
  C. 5a non-reactive    — the designed target: conservation holds by construction
  D. 5a reactive        — the sorted reactive model conserves too
  E. 5b equivalence     — reactive-with-rates-zeroed == non-reactive
  F. NEGATIVE control   — a deliberately mis-wired comparison MUST fail, or the gate is vacuous

Slow: four DTT runs. Exit 0 = all pass.
"""
from __future__ import annotations

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import tracer_test as tt

H = pathlib.Path(r"C:\Users\DELL\AppData\Local\Temp\slc_rev")
NONREACTIVE_DLL, NONREACTIVE_XML = H / "out" / "final.dll", H / "out" / "final.xml"
REACTIVE_DLL, REACTIVE_XML = H / "out" / "r25_sorted.dll", H / "out" / "r25_sorted.xml"
NOSORT_DLL, NOSORT_XML = H / "out" / "r24_diffcalc.dll", H / "out" / "r24_diffcalc.xml"

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f" - {detail}" if detail else ""))


def main() -> int:
    print("A. static guards")
    r = tt.run_model(H / "out" / "does_not_exist.dll", ["Sumo__Time"], ["mode dynamic", "start"])
    check("a missing model is refused at preflight", not r["ok"] and r["stage"] == "preflight")
    roles = tt.state_variable_roles(NONREACTIVE_XML)
    check("roles are read from the XML", len(roles) > 50, f"{len(roles)} variables classified")
    check("SO2 is classified SystemState (set-handled, not conserved)",
          roles.get("SO2") == "SystemState")
    check("SVFA is classified StateVariable (genuinely conserved)",
          roles.get("SVFA") == "StateVariable")
    _, zinfo = tt.zero_rate_commands(REACTIVE_XML)
    check("rate-zeroing reports which aeration params were ABSENT rather than skipping silently",
          "aeration_absent" in zinfo, str(zinfo.get("aeration_absent")))
    check("rate-zeroing found the rate parameters", zinfo["n_rate_params"] > 50,
          f"{zinfo['n_rate_params']} rate params")

    print("\nB. the sentinel guard — a -nosort build must be REFUSED")
    if NOSORT_DLL.exists():
        rn = tt.rung5a_conservative_tracer(NOSORT_DLL, NOSORT_XML, horizon_days=1.0,
                                           timeout_s=420)
        check("the -nosort build is refused, not measured",
              not rn["ok"] and rn.get("stage") == "sentinel", rn.get("reason", ""))
        check("the refusal names the frozen variables", bool(rn.get("frozen")),
              str(rn.get("frozen", []))[:70])
    else:
        check("-nosort artefact available for the sentinel test", False, str(NOSORT_DLL))

    print("\nC. rung 5a on the NON-REACTIVE model (the designed target)")
    a = tt.rung5a_conservative_tracer(NONREACTIVE_DLL, NONREACTIVE_XML, horizon_days=20.0,
                                      timeout_s=600)
    check("5a passes", a["ok"], a.get("reason", ""))
    check("flow is conserved exactly", a.get("q_rel") == 0.0,
          f"q_in={a.get('q_in')} q_out={a.get('q_out')}")
    check("zero component imbalances", a.get("n_imbalances") == 0)
    check("worst residual is at machine precision", (a.get("worst_rel") or 1) < 1e-12,
          f"worst={a.get('worst_rel'):.3g} on {a.get('worst_component')}")
    check("SystemStates are exempted by design, not silently dropped",
          a.get("n_exempt_by_design", 0) > 0, f"{a.get('n_exempt_by_design')} exempt")

    print("\nD. rung 5a on the SORTED REACTIVE model")
    b = tt.rung5a_conservative_tracer(REACTIVE_DLL, REACTIVE_XML, horizon_days=20.0,
                                      timeout_s=600)
    check("5a passes on the reactive model too", b["ok"], b.get("reason", ""))
    check("no derived variable is frozen at the sentinel", b.get("stage") == "complete")
    check("worst residual at machine precision", (b.get("worst_rel") or 1) < 1e-12,
          f"worst={b.get('worst_rel'):.3g}")

    print("\nE. rung 5b — degenerate equivalence (previously UNEXERCISED)")
    e = tt.rung5b_degenerate_equivalence(REACTIVE_DLL, REACTIVE_XML,
                                         NONREACTIVE_DLL, NONREACTIVE_XML,
                                         horizon_days=20.0, timeout_s=600)
    check("5b passes: reactive-with-rates-zeroed == non-reactive", e["ok"],
          e.get("reason", ""))
    check("a meaningful number of components were compared", e.get("n_compared", 0) >= 50,
          f"{e.get('n_compared')} compared, {e.get('n_exempt_by_design')} exempt")
    check("worst difference is negligible", (e.get("worst_rel") or 1) < 1e-6,
          f"worst={e.get('worst_rel'):.3g} on {e.get('worst_component')}")
    check("role mismatches between the models are REPORTED, not hidden",
          "role_mismatch" in e, str(e.get("role_mismatch")))

    print("\nF. NEGATIVE control — the gate must be able to fail")
    # Compare the inlet port against itself shifted: a deliberately wrong out_port means the
    # flux comparison is between unrelated variables and MUST be reported as failure.
    n = tt.rung5a_conservative_tracer(NONREACTIVE_DLL, NONREACTIVE_XML,
                                      in_port="Inflpipe", out_port="Influentoutp",
                                      horizon_days=1.0, timeout_s=420)
    check("a mis-wired port comparison does NOT silently pass", not n["ok"],
          f"{n.get('stage')}: {n.get('reason','')[:60]}")
    # and a tolerance of zero must fail on real floating point
    z = tt.rung5a_conservative_tracer(NONREACTIVE_DLL, NONREACTIVE_XML, horizon_days=20.0,
                                      tol=0.0, timeout_s=600)
    check("tol=0 fails on genuine floating-point residue (the check is not vacuous)",
          not z["ok"], f"{z.get('n_imbalances')} imbalance(s) at tol=0")

    bad = [nm for nm, ok, _ in results if not ok]
    print("\n" + "=" * 66)
    print(f"GATE E: {len(results) - len(bad)}/{len(results)} passed"
          + ("" if not bad else f"\nFAILED: {bad}"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
