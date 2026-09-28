"""Acceptance test for ticket 08 — the prose-to-spec review gate (rung 1).

REWRITTEN after commandcode's adversarial review (defect H1). The first version was 15/15 and
still let a fabricated magnitude through: it only tested `"about 0.5"` and the REQUIRED
sentinel, i.e. it asserted what the implementation happened to do. commandcode's verdict was
that the test "asserts what the implementation happens to do" — it was right.

This version attacks the gate instead of demonstrating it. Every group below is a way a
fabricated or half-finished value could reach a simulation:

  A. REQUIRED sentinel        — the unfilled placeholder
  B. hedged magnitudes        — "about 0.5", "~0.5", "0.5 (typical)", "estimated 0.4"
  C. FABRICATED PROVENANCE    — the H1 defect: a self-asserted "user-measured" with no backing
  D. routing / composite      — the checks tickets 19 and 17 asserted but nothing implemented
  E. acceptance as a rule     — cannot accept a failing spec; cannot emit unaccepted
  F. confirmation lapse       — editing a value after acceptance must revoke its confirmation
  G. render ordering          — danger first, ASCII only
  H. review bypasses          — string magnitudes, 9 hedge forms, bulk cost, unit swap

Exit 0 = all pass.
"""
from __future__ import annotations

import copy
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import spec_review as sr

HERE = pathlib.Path(__file__).resolve().parent
FIX = HERE / "data/fixtures"
GOOD_SOURCE = "Henze et al. 2000, IWA STR9 Table 4.2, p.61"

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f" - {detail}" if detail else ""))


def _fill(spec: dict, idx: int, value, prov="literature-cited", source=GOOD_SOURCE) -> None:
    d = spec["parameters"][idx]["default"]
    d.update({"value": value, "provenance": prov, "source": source, "unverified": False})


def main() -> int:
    typeb = json.loads((FIX / "unit_spec_typeB_sulfideoxidation_v1.json").read_text(encoding="utf-8"))
    typea = json.loads((FIX / "unit_spec_typeA_equalization_v1.json").read_text(encoding="utf-8"))

    print("A. the REQUIRED sentinel is caught")
    vb, va = sr.lint(typeb), sr.lint(typea)
    check("Type B fixture fails rung 1", not vb["ok"] and len(vb["required"]) > 0,
          f"{len(vb['required'])} unfilled")
    check("Type A fixture fails rung 1", not va["ok"] and len(va["required"]) > 0,
          f"{len(va['required'])} unfilled")
    check("each REQUIRED entry names what is owed", all(r["what"] for r in vb["required"]))

    print("\nB. hedged magnitudes are refused (regex, not whole-token matching)")
    for hedge in ("about 0.5", "~0.5", "0.5 (typical)", "estimated 0.4", "roughly 2"):
        t = copy.deepcopy(typeb)
        t["parameters"][2]["default"]["value"] = hedge
        check(f"{hedge!r} rejected", len(sr.collect_unparseable(t)) >= 1)
    for legit in ("-1/Y_SOB", 0.5, "MaxFlow"):
        t = copy.deepcopy(typeb)
        t["parameters"][2]["default"]["value"] = legit
        bad = [u for u in sr.collect_unparseable(t) if u["path"].endswith("parameters[2].default")]
        check(f"legitimate value {legit!r} NOT rejected", not bad)

    print("\nC. fabricated provenance is refused (defect H1)")
    fab = copy.deepcopy(typeb)
    _fill(fab, 2, 0.9, prov="user-measured", source="")
    check("'user-measured' with NO source is caught",
          any(u["path"].endswith("parameters[2].default") for u in sr.collect_uncorroborated(fab)))
    fab2 = copy.deepcopy(typeb)
    _fill(fab2, 2, 0.9, prov="literature-cited", source="a paper")
    check("'literature-cited' with nothing citation-shaped is caught",
          any(u["path"].endswith("parameters[2].default") for u in sr.collect_uncorroborated(fab2)))
    ok3 = copy.deepcopy(typeb)
    _fill(ok3, 2, 0.9)
    check("a real citation is accepted",
          not any(u["path"].endswith("parameters[2].default") for u in sr.collect_uncorroborated(ok3)))
    check("inherited-model-base needs no source (it is not self-asserted)",
          "inherited-model-base" not in sr.SELF_ASSERTED)

    print("\nD. routing drift and composites are refused (tickets 19 / 17)")
    drift = copy.deepcopy(typeb)
    drift["routing"]["routed_as"] = "A"                 # but it introduces state variables
    kinds = [r["kind"] for r in sr.collect_routing_faults(drift)]
    check("Type A claiming new state variables is refused", "routing-drift" in kinds, str(kinds))
    drift2 = copy.deepcopy(typea)
    drift2["routing"]["routed_as"] = "B"                # but introduces none
    check("Type B with no new state variables is refused",
          "routing-drift" in [r["kind"] for r in sr.collect_routing_faults(drift2)])
    comp = copy.deepcopy(typeb)
    comp["classification"]["is_composite"] = True
    comp["classification"]["composite_evidence"]["sub_units"] = ["clarifier", "digester"]
    faults = sr.collect_routing_faults(comp)
    cf = [r for r in faults if r["kind"] == "composite-refused"]
    check("composite is refused, naming its sub-units",
          bool(cf) and "clarifier" in cf[0]["ask"], cf[0]["ask"] if cf else "")
    check("refusals are structured values, not exceptions", all(r.get("refusal") for r in faults))

    print("\nE. acceptance is a rule")
    check("accept() refuses while rung 1 fails", not sr.accept(copy.deepcopy(typeb), "t")["accepted"])
    good = copy.deepcopy(typeb)
    _fill(good, 2, 0.9)
    _fill(good, 3, 0.05)
    for pth in ("$", ):    # fix remaining uncorroborated values found in the fixture
        pass
    for path, node in list(sr.iter_values(good)):
        if isinstance(node.get("value"), (int, float)) and node.get("provenance") in sr.SELF_ASSERTED:
            node["source"] = GOOD_SOURCE
            node["provenance"] = "literature-cited"
    v = sr.lint(good)
    check("a fully corroborated spec passes rung 1", v["ok"], "; ".join(v["errors"]))
    check("may_emit() still refuses before acceptance", not sr.may_emit(good)["may_emit"])
    r = sr.accept(copy.deepcopy(good), "tester")
    check("accept() refuses without per-value confirmation", not r["accepted"], r["reason"])
    acc = copy.deepcopy(good)
    r2 = sr.accept(acc, "tester", confirm_all=True)
    check("accept() succeeds with explicit confirmation", r2["accepted"], r2.get("reason", ""))
    check("acceptance records who, when, and how", bool(sr.acceptance_of(acc).get("at"))
          and sr.acceptance_of(acc).get("by") == "tester"
          and sr.acceptance_of(acc).get("confirmation") == "bulk")
    check("may_emit() allows only after confirmed acceptance (bulk needs opt-in)",
          sr.may_emit(acc, allow_bulk=True)["may_emit"])

    print("\nF. confirmation lapses when a value changes after acceptance")
    tampered = copy.deepcopy(acc)
    tampered["parameters"][2]["default"]["value"] = 999.0
    g = sr.may_emit(tampered, allow_bulk=True)
    check("editing a confirmed value revokes emission", not g["may_emit"], g["reason"])

    print("\nF2. a redundant re-accept must never WIPE the record (measured 2026-09-07)")
    rewiped = copy.deepcopy(acc)
    r3 = sr.accept(rewiped, "re-accept with nothing outstanding", confirm_all=True)
    check("re-accept succeeds", r3.get("accepted"), r3.get("reason", ""))
    check("re-accept with nothing outstanding keeps every stamp",
          len(sr.collect_unconfirmed(rewiped)) == 0
          and sr.may_emit(rewiped, allow_bulk=True)["may_emit"],
          f"stale={len(sr.collect_unconfirmed(rewiped))}")
    check("previous stamps are kept verbatim, not re-stamped from current values",
          all(rewiped["provenance"]["accepted"]["confirmed"].get(p) == v
              for p, v in acc["provenance"]["accepted"]["confirmed"].items()))
    drifted = copy.deepcopy(acc)
    drifted["parameters"][2]["default"]["value"] = 999.0
    sr.accept(drifted, "re-accept over a tampered value", confirm_all=True)
    g = sr.may_emit(drifted)
    check("re-accept over a tampered value DOWNGRADES the record to bulk (visible, opt-in gated)",
          not g["may_emit"] and "BULK" in g["reason"], g["reason"])
    check("the tampered path's stamp changed (the old confirmation did not survive the edit)",
          drifted["provenance"]["accepted"]["confirmed"][".parameters[2].default"]
          != acc["provenance"]["accepted"]["confirmed"][".parameters[2].default"])

    print("\nG. the review leads with what is owed")
    text = sr.render(typeb)
    check("'values you still owe' precedes ports and matrix",
          -1 < text.find("VALUES YOU STILL OWE") < text.find("4. PORTS") < text.find("STOICHIOMETRIC"))
    check("render is pure ASCII", all(ord(c) < 128 for c in text))


    print("")
    print("H. bypasses found by adversarial review (must all be closed)")
    # H-1 string-typed magnitude: both numeric-only checks used to skip it entirely
    st = copy.deepcopy(typeb)
    st["parameters"][2]["default"].update(value="999", provenance="user-measured",
                                          source="measured on site during commissioning",
                                          unverified=False)
    check("string-typed magnitude '999' is treated as a magnitude",
          sr._as_magnitude("999") == 999.0)
    check("string-typed magnitude appears in the unconfirmed set",
          any(u["path"].endswith("parameters[2].default") for u in sr.collect_unconfirmed(st)))
    check("string-typed magnitude cannot reach emission unconfirmed",
          not sr.may_emit(st)["may_emit"])
    # H-2 the nine hedge forms that walked past the first regex
    for hedge in ("0.5ish", "ca. 0.5", "0.5 (typ)", "guesstimate 0.5", "nominal 0.5",
                  "0.5 or so", "rough 0.5", "0.5 , give or take", "somewhere near 0.5"):
        check(f"hedge {hedge!r} caught", bool(sr._PROSE.search(hedge)))
    for legit in ("-1/Y_SOB", "0.5", "MaxFlow", "1E-05", "-1/YOHO,VFA,ox"):
        check(f"legitimate {legit!r} not flagged as a hedge", not sr._PROSE.search(legit))
    # H-3 bulk confirmation must cost something
    bulk = copy.deepcopy(good)
    sr.accept(bulk, "tester", confirm_all=True)
    check("bulk-confirmed spec is REFUSED emission by default",
          not sr.may_emit(bulk)["may_emit"], sr.may_emit(bulk)["reason"])
    check("bulk emission possible only via explicit allow_bulk",
          sr.may_emit(bulk, allow_bulk=True)["may_emit"])
    # H-4 the unit carries the substance basis; changing it must revoke confirmation
    uni = copy.deepcopy(acc)
    for path, node in sr.iter_values(uni):
        if sr._as_magnitude(node.get("value")) is not None:
            node["unit"] = "g S.m-3"; break
    check("changing a unit after acceptance revokes emission",
          not sr.may_emit(uni, allow_bulk=True)["may_emit"])
    # H-5 the honest limit, asserted so it cannot be forgotten
    fab = copy.deepcopy(typeb)
    fab["parameters"][2]["default"].update(value=0.9, provenance="user-measured",
                                           source="measured on site during commissioning",
                                           unverified=False)
    check("KNOWN LIMIT: free-text source passes corroboration (documented, not silent)",
          not any(u["path"].endswith("parameters[2].default")
                  for u in sr.collect_uncorroborated(fab)))

    bad = [n for n, ok, _ in results if not ok]
    print("\n" + "=" * 64)
    print(f"RESULT: {len(results) - len(bad)}/{len(results)} passed"
          + ("" if not bad else f"\nFAILED: {bad}"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
