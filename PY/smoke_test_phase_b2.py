"""Gate B2 — acceptance test for ticket 12 Phase B2 (rung 2.5, the additive-only diff gate).

Rung 2.5 is the load-bearing condition of ticket 18's calibrated-plant policy: adding a Type B
unit to a calibrated plant is permissible ONLY behind a passing additive-only diff. Nothing built
it until now, and Gate G's ladder originally skipped it entirely (defect H2 of the first review).

  A. reader stability   — vendor vs itself must diff to NOTHING, or every later verdict is noise
  B. REAL additive fork — a genuinely added parameter is classified `added` and PASSES
  C. REAL modified fork — a changed vendor coefficient is classified `modified` and FAILS
  D. removal            — a removed symbol FAILS
  E. Q14 teeth 3 and 4  — the stamp, and the disable-on-failure admission rule
  F. gate-as-input      — the admission tool must REFUSE when handed no gate result

Forks are written with Excel COM (`.xlsm` cannot be written by xlsxwriter, and openpyxl drops
~124 symbol-map entries through sharedStrings loss). The vendor workbook is NEVER modified.

Exit 0 = all pass.
"""
from __future__ import annotations

import copy
import pathlib
import shutil
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import model_base_diff as mbd

VENDOR = pathlib.Path(r"D:\SUMO24\Process code\Model base\Focus models\Sumo2C.xlsm")
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f" - {detail}" if detail else ""))


def _fork(dst: pathlib.Path, edits) -> bool:
    """Copy the vendor base and apply `edits(worksheet_getter)` via Excel COM."""
    import win32com.client as win32
    shutil.copyfile(VENDOR, dst)
    app = win32.gencache.EnsureDispatch("Excel.Application")
    app.Visible = False
    app.DisplayAlerts = False
    try:
        wb = app.Workbooks.Open(str(dst))
        try:
            edits(wb)
            wb.Save()
        finally:
            wb.Close(SaveChanges=True)
    finally:
        app.Quit()
    return dst.exists()


def _find_symbol_row(ws, symbol: str, max_row: int = 400, sym_col: int = 2):
    for r in range(1, max_row):
        v = ws.Cells(r, sym_col).Value
        if v is not None and str(v).strip() == symbol:
            return r
    return None


def main() -> int:
    if not VENDOR.exists():
        print(f"vendor model base not found: {VENDOR}")
        return 1
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="gate_b2_"))
    vendor_mtime = VENDOR.stat().st_mtime

    print("A. reader stability")
    d0 = mbd.diff_model_bases(VENDOR, VENDOR)
    check("vendor vs itself diffs to nothing",
          d0["n_added"] == 0 and d0["n_modified"] == 0 and d0["n_removed"] == 0,
          f"+{d0['n_added']} ~{d0['n_modified']} -{d0['n_removed']}")
    check("the value sheets were actually read", len(d0["sheets_compared"]) >= 4,
          str(d0["sheets_compared"]))
    base = mbd.read_model_base(VENDOR)
    check("Parameters carries a meaningful symbol count",
          len(base.get("Parameters", {})) > 50, f"{len(base.get('Parameters', {}))} symbols")
    check("the Gujer matrix was parsed by process id",
          len(base.get("Model", {})) > 50, f"{len(base.get('Model', {}))} processes")

    print("\nB. REAL additive fork (a new parameter)")
    add_fork = tmp / "Sumo2C_added.xlsm"

    def _add(wb):
        ws = wb.Worksheets("other parameters")
        r = _find_symbol_row(ws, "fKS") or 4
        ws.Cells(r + 1, 2).Value = "kHH_TESTADD"
        ws.Cells(r + 1, 3).Value = "Gate B2 synthetic added parameter"
        ws.Cells(r + 1, 4).Value = 0.42

    ok = _fork(add_fork, _add)
    check("additive fork written via Excel COM", ok)
    if ok:
        da = mbd.diff_model_bases(VENDOR, add_fork)
        ga = mbd.additive_only_gate(da)
        check("the added symbol is classified `added`",
              any(a["symbol"] == "kHH_TESTADD" for a in da["added"]),
              f"+{da['n_added']} ~{da['n_modified']} -{da['n_removed']}")
        check("an additive fork PASSES the gate", ga["ok"], ga["reason"][:70])

    print("\nC. REAL modified fork (a changed vendor coefficient)")
    mod_fork = tmp / "Sumo2C_modified.xlsm"

    def _mod(wb):
        ws = wb.Worksheets("other parameters")
        r = _find_symbol_row(ws, "fKS")
        if r:
            ws.Cells(r, 4).Value = 0.999          # was 0.1

    ok = _fork(mod_fork, _mod)
    check("modified fork written via Excel COM", ok)
    if ok:
        dm = mbd.diff_model_bases(VENDOR, mod_fork)
        gm = mbd.additive_only_gate(dm)
        check("the changed value is classified `modified`",
              any(m["symbol"] == "fKS" for m in dm["modified"]),
              f"~{dm['n_modified']}")
        check("a modified fork FAILS the gate", not gm["ok"], gm["reason"][:70])
        check("the failure names the offending symbol",
              any(m.get("symbol") == "fKS" for m in gm.get("modified", [])))

    print("\nD. removal fails too")
    dr = {"added": [], "modified": [], "removed": [{"sheet": "Parameters", "symbol": "muOHO"}],
          "n_added": 0, "n_modified": 0, "n_removed": 1}
    check("a removed symbol FAILS the gate", not mbd.additive_only_gate(dr)["ok"])

    print("\nE. Q14 teeth 3 and 4")
    spec = {"routing": {"routed_as": "B"}, "provenance": {}}
    st = mbd.stamp_verification_state(copy.deepcopy(spec), continuity_ok=True)
    check("tooth 3 stamps 'stoichiometry-verified, kinetically-unverified'",
          st["stamped"] == "stoichiometry-verified, kinetically-unverified", st["stamped"])
    st2 = mbd.stamp_verification_state(copy.deepcopy(spec), continuity_ok=False)
    check("a failed continuity stamps UNVERIFIED", "UNVERIFIED" in st2["stamped"], st2["stamped"])
    good_gate = {"ok": True, "gate": "additive-only"}
    bad_gate = {"ok": False, "gate": "additive-only", "reason": "modified"}
    adm = mbd.type_b_admission(copy.deepcopy(spec), good_gate, continuity_ok=True)
    check("tooth 4 admits an additive, continuity-clean Type B unit", adm["admitted"])
    check("...and carries the kinetics caveat forward", "kinetics" in adm.get("caveat", ""))
    dis = mbd.type_b_admission(copy.deepcopy(spec), bad_gate, continuity_ok=True)
    check("tooth 4 DISABLES a unit whose fork failed the gate",
          not dis["admitted"] and dis.get("disabled"), dis["reason"][:60])
    dis2 = mbd.type_b_admission(copy.deepcopy(spec), good_gate, continuity_ok=False)
    check("tooth 4 DISABLES a unit whose continuity failed", not dis2["admitted"])
    a_only = mbd.type_b_admission({"routing": {"routed_as": "A"}}, None, continuity_ok=True)
    check("a Type A unit is unaffected by rung 2.5", a_only["admitted"])

    print("\nF. the gate result is an INPUT, never recomputed")
    none_gate = mbd.type_b_admission(copy.deepcopy(spec), None, continuity_ok=True)
    check("admission REFUSES when handed no gate result",
          not none_gate["admitted"], none_gate["reason"][:60])
    check("the refusal explains why it cannot self-compute",
          "INPUT" in " ".join(none_gate.get("detail", [])))

    print("\nG. the vendor workbook was never touched")
    check("vendor mtime unchanged", VENDOR.stat().st_mtime == vendor_mtime)
    check("vendor still read-only", not (VENDOR.stat().st_mode & 0o222))

    shutil.rmtree(tmp, ignore_errors=True)
    bad = [n for n, ok, _ in results if not ok]
    print("\n" + "=" * 66)
    print(f"GATE B2: {len(results) - len(bad)}/{len(results)} passed"
          + ("" if not bad else f"\nFAILED: {bad}"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
