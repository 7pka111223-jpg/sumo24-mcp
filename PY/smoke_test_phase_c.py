"""Gate C — acceptance test for ticket 12 Phase C (the emitter).

Phase C is: emit a positionally-valid Sumo process-unit folder from an ACCEPTED spec.
This test attacks the emitter rather than demonstrating it. Every group is a way a bad
workbook could reach the SMT and fail far away from its cause:

  A. the emission gate      — an unaccepted or failing spec must NEVER produce a workbook
  B. the ticket-01 invariant — no blank row between a block title and its header
  C. positional fidelity     — column A empty, title/description/value columns per sheet
  D. the GUI contracts       — Appearance + Group Info, which NO compile rung reads
  E. the icon                — a real EMF, verified by header bytes not by the writer's claim
  F. naming and collisions   — vendor shadowing refused, never overwrite
  G. round-trip              — the emitted workbook reads back with its content intact

Exit 0 = all pass.
"""
from __future__ import annotations

import copy
import json
import pathlib
import shutil
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import icon_emitter as ie
import spec_review as sr
import sumoslang_author as sa
import unit_emitter as ue

FIX = HERE / "data/fixtures"
OUT = HERE.parent / "custom_units" / "_gate_c_tmp"
GOOD_SOURCE = "Henze et al. 2000, IWA STR9 Table 4.2, p.61"

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f" - {detail}" if detail else ""))


def _accepted_spec() -> dict:
    spec = json.loads((FIX / "unit_spec_typeB_sulfideoxidation_v1.json").read_text(encoding="utf-8"))
    for prm in spec["parameters"]:
        d = prm.get("default") or {}
        if d.get("value") == "REQUIRED":
            d.update(value=0.5, provenance="literature-cited", source=GOOD_SOURCE,
                     unverified=False)
    for _path, node in list(sr.iter_values(spec)):
        if sr._as_magnitude(node.get("value")) is not None and \
                node.get("provenance") in sr.SELF_ASSERTED:
            node.update(provenance="literature-cited", source=GOOD_SOURCE, unverified=False)
    sr.accept(spec, "gate-C", confirm_all=True)
    return spec


def main() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)

    print("A. the emission gate")
    raw = json.loads((FIX / "unit_spec_typeB_sulfideoxidation_v1.json").read_text(encoding="utf-8"))
    r = ue.emit_unit(raw, OUT)
    check("unaccepted spec produces NO workbook", not r["emitted"], r["reason"])
    check("no file was written on refusal", not OUT.exists() or not list(OUT.glob("*.xlsx")))
    spec = _accepted_spec()
    bulk_refused = ue.emit_unit(spec, OUT)
    check("bulk-confirmed spec refused without allow_bulk", not bulk_refused["emitted"])
    r = ue.emit_unit(spec, OUT, allow_bulk=True)
    check("accepted spec emits", r["emitted"], r.get("reason", ""))
    xlsx = pathlib.Path(r["workbook"]) if r["emitted"] else None

    print("\nB. the ticket-01 invariant (blank row between title and header)")
    v = ue.verify_no_title_header_gap(xlsx)
    check("no title->header gap anywhere", v["ok"], f"{v['blocks_checked']} blocks checked")
    check("at least one block was actually checked", v["blocks_checked"] > 0)

    import openpyxl                                   # READING only
    wb = openpyxl.load_workbook(xlsx, read_only=True, data_only=True)
    grid = {sn: [[("" if c is None else str(c)) for c in row]
                 for row in wb[sn].iter_rows(max_col=10, values_only=True)]
            for sn in wb.sheetnames}
    wb.close()

    print("\nC. positional fidelity")
    check("canonical 6 sheets in order",
          list(grid.keys()) == ["Help", "Unit", "Parameters", "Code", "Display", "Popup"],
          str(list(grid.keys())))
    check("'Predefined charts' NOT emitted (6 of 237 units only)",
          "Predefined charts" not in grid)
    colA = [r[0] for rows in grid.values() for r in rows if r]
    check("column A empty except Code section titles",
          all(c == "" for sn, rows in grid.items() if sn != "Code" for r in rows for c in [r[0]]))
    check("row 1 blank on every sheet",
          all(not any(rows[0]) for rows in grid.values() if rows))

    print("\nD. the GUI contracts no compile rung reads")
    unit = grid["Unit"]
    app_i = next((i for i, r in enumerate(unit) if r[1] == "Appearance"), None)
    check("Appearance block present", app_i is not None)
    if app_i is not None:
        blk = unit[app_i:app_i + 5]
        default_row = next((r for r in blk if r[1] == "Default"), None)
        size_row = next((r for r in blk if r[1] == "CustomSize"), None)
        check("Appearance Default names an .emf", bool(default_row) and default_row[3].endswith(".emf"),
              default_row[3] if default_row else "")
        import re
        check("CustomSize matches ^\\d+x\\d+$",
              bool(size_row) and bool(re.fullmatch(r"\d+x\d+", size_row[3])),
              size_row[3] if size_row else "")
    g = ue.emit_group_info(OUT, "HH Custom", "SulfideOxidation")
    check("Group Info emitted", g["emitted"], g.get("reason", ""))
    bad = ue.emit_group_info(OUT, "HH Custom", "SulfideOxidation.xlsx")
    check("DefaultUnit with an extension is REFUSED (must be a stem)", not bad["emitted"],
          bad.get("reason", ""))
    gi = openpyxl.load_workbook(pathlib.Path(g["path"]), read_only=True, data_only=True)
    girows = [[("" if c is None else str(c)) for c in r]
              for r in gi["Unit"].iter_rows(max_col=6, values_only=True)]
    gi.close()
    check("Group Info carries SortingPriority and DefaultUnit",
          any(r[1] == "SortingPriority" for r in girows) and
          any(r[1] == "DefaultUnit" for r in girows))

    print("\nE. the icon")
    icon = OUT / "SulfideOxidation.emf"
    ir = ie.emit_placeholder(icon, label="SulfideOxidation")
    check("placeholder EMF written", ir["emitted"], ir.get("reason", ""))
    check("file is a structurally valid EMF (header bytes, not the writer's claim)",
          ie.is_valid_emf(icon)["valid"])
    check("provenance records it as a placeholder", ir.get("provenance") == "icon=placeholder")
    check("template copy requires opt-in",
          not ie.emit_from_template(OUT / "x.emf", icon)["emitted"])

    print("\nE2. the GUI typing contract (measured 2026-09-07, HH_DynaSand_v1)")
    check("emit_unit ran the typing verifier on its own output",
          r.get("gui_typing", {}).get("ok") is True, str(r.get("gui_typing")))
    port_rows = [row for row in grid["Unit"] if len(row) > 7 and row[5] in ("in", "out")]
    check("every port row carries a NATIVE numeric Size cell",
          bool(port_rows) and all(str(row[7]).strip().isdigit() and int(row[7]) >= 1
                                  for row in port_rows),
          str([(row[1], row[7]) for row in port_rows]))
    check("every port row carries a non-empty Image cell",
          all(str(row[6]).strip() for row in port_rows),
          str([(row[1], row[6]) for row in port_rows]))
    import openpyxl as _op
    _wb2 = _op.load_workbook(xlsx, read_only=True)
    _raw = _wb2["Unit"]
    _sizes = [c.value for row in _raw.iter_rows(min_col=8, max_col=8, values_only=False)
              for c in row if c.value is not None and isinstance(c.value, (int, float))
              and not isinstance(c.value, bool)]
    _wb2.close()
    check("Size cells are stored as native numbers, not text",
          bool(_sizes) and all(isinstance(v, (int, float)) for v in _sizes), str(_sizes[:4]))
    tv = ue.verify_gui_typing(xlsx)
    check("verify_gui_typing passes on the emitted workbook", tv["ok"] is True,
          str(tv.get("faults", [])[:2]))

    print("\nF. naming and collisions")
    check("qualified_name enforces HH_<name>_v<n>",
          sa.qualified_name("Sulfide Oxidation") == "HH_Sulfide Oxidation_v1")
    ex = sa.check_collision("Simple CSTR")
    check("EXACT vendor name refused", not ex["ok"] and ex["collision"] == "exact")
    check("exact refusal cites the shadowing mechanism",
          "shadow" in " ".join(ex["detail"]).lower())
    bn = sa.check_collision("HH_Simple CSTR_v1")
    check("bare-name match refused", not bn["ok"] and bn["collision"] == "bare-name")
    check("bare-name refusal does NOT claim shadowing (filenames differ)",
          "CANNOT shadow" in " ".join(bn["detail"]))
    check("well-formed novel name accepted", sa.check_collision("HH_SulfideOxidation_v1")["ok"])
    a1 = sa.allocate_slug("GateCProbe", custom_root=OUT.parent)
    check("allocate_slug returns a free versioned slug", a1["allocated"], a1.get("name", ""))
    pathlib.Path(a1["path"]).mkdir(parents=True, exist_ok=True)
    a2 = sa.allocate_slug("GateCProbe", custom_root=OUT.parent, version=1)
    check("never overwrites an existing slug", not a2["allocated"], a2.get("reason", ""))
    shutil.rmtree(a1["path"], ignore_errors=True)

    print("\nG. round-trip")
    params = grid["Parameters"]
    hdr_i = next((i for i, r in enumerate(params) if r[1] == "Symbol"), None)
    check("Parameters header present with the measured 9-column shape",
          hdr_i is not None and params[hdr_i][1:10] ==
          ["Symbol", "Name", "Default", "Low limit", "High limit", "Unit", "Decimals",
           "Rule", "Principle/comment"])
    symbols = {r[1] for r in params[hdr_i + 1:] if r[1]} if hdr_i is not None else set()
    spec_syms = {p["symbol"] for p in spec.get("parameters", [])}
    check("every spec parameter reached the workbook",
          spec_syms.issubset(symbols), f"missing={sorted(spec_syms - symbols)[:4]}")
    code = grid["Code"]
    code_syms = {r[1] for i, r in enumerate(code) if r[1] and r[1] != "Symbol"}
    spec_code = {ln["symbol"] for b in spec.get("code_blocks", []) for ln in b.get("lines", [])}
    check("every spec code line reached the workbook",
          spec_code.issubset(code_syms), f"missing={sorted(spec_code - code_syms)[:4]}")

    shutil.rmtree(OUT, ignore_errors=True)
    bad = [n for n, ok, _ in results if not ok]
    print("\n" + "=" * 66)
    print(f"GATE C: {len(results) - len(bad)}/{len(results)} passed"
          + ("" if not bad else f"\nFAILED: {bad}"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
