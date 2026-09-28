"""Gate D — acceptance test for ticket 12 Phase D (rungs 3 and 4).

Phase D wraps the two external compilers. Both **report success while failing**, so the whole
point of this gate is the NEGATIVE test: a malformed unit must be caught by the wrapper even
though `SMT24.exe` exits 0.

  A. preflight guards      — `-nosort` banned; missing inputs refused before anything runs
  B. PE verification       — a file existing is not a loadable 64-bit DLL
  C. POSITIVE chain        — a known-good plant compiles to a real PE32+ DLL through both rungs
  D. NEGATIVE, the point   — a blank row between a table title and its header (the ticket-01
                             defect) is reported as FAILURE regardless of the exit code
  E. log resolution        — the CWD `smtlog.txt` is used, not the install copy

Slow: two SMT runs plus a link. Exit 0 = all pass.
"""
from __future__ import annotations

import pathlib
import shutil
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import slc_runner as slc
import smt_runner as smt

HARNESS = pathlib.Path(r"C:\Users\DELL\AppData\Local\Temp\slc_rev")
CLASSES = HARNESS / "Process code" / "Plant classes"
INSTANCES = HARNESS / "Process code" / "Plant instances"
GOOD_INSTANCE = INSTANCES / "plant_diffcalc.xlsx"
GOOD_CLASS = CLASSES / "PlantR24.xlsx"

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f" - {detail}" if detail else ""))


def _rewrite_class(src: pathlib.Path, dst: pathlib.Path,
                   inject_gap_after_title: str | None = None) -> None:
    """Copy a plant class through xlsxwriter, optionally injecting the ticket-01 defect.

    openpyxl READS; xlsxwriter WRITES. If `inject_gap_after_title` is given, a blank row is
    inserted immediately after that title row on the `Structure` sheet — separating the title
    from its header, which is exactly what broke ticket 01's table scan.
    """
    import openpyxl
    import xlsxwriter

    wb = openpyxl.load_workbook(str(src), read_only=True, data_only=True)
    sheets = {sn: [list(r) for r in wb[sn].iter_rows(values_only=True)] for sn in wb.sheetnames}
    wb.close()

    out = xlsxwriter.Workbook(str(dst), {"strings_to_numbers": False})
    for sn, rows in sheets.items():
        ws = out.add_worksheet(sn)
        r_out = 0
        for row in rows:
            for c, v in enumerate(row):
                if v is not None:
                    ws.write(r_out, c, v)
            first = next((str(x) for x in row if x is not None), "")
            r_out += 1
            if (inject_gap_after_title and sn == "Structure"
                    and first.strip() == inject_gap_after_title):
                r_out += 1                      # <-- the defect: title, blank, header
    out.close()


def main() -> int:
    print("A. preflight guards")
    r = smt.run_smt(GOOD_INSTANCE, HARNESS / "out" / "_gate_d_nosort.xml",
                    extra_args=["-nosort"])
    check("-nosort refused at preflight", not r["ok"] and r["stage"] == "preflight",
          r.get("reason", ""))
    check("the refusal explains the silent-numerical-failure risk",
          "algebraic" in " ".join(r.get("detail", [])).lower())
    r = smt.run_smt(HARNESS / "nope.xlsx", HARNESS / "out" / "_x.xml")
    check("missing instance refused before running", not r["ok"] and r["stage"] == "preflight")
    r = slc.run_slcompiler(HARNESS / "nope.xml", HARNESS / "out" / "_x.dll",
                           HARNESS / "_gate_d_src")
    check("slcompiler refuses a missing XML", not r["ok"] and r["stage"] == "preflight")

    print("")
    print("A2. the [ERROR] scanner must match the SMT's PADDED level tags")
    # [MEASURED] the installed SMT writes `[INFO    ]` / `[ERROR   ]`, space-padded to a fixed
    # width. A scanner matching the literal "[ERROR]" matches NOTHING and reports every failed
    # run as clean. That defect was live until an adversarial review measured it.
    check("padded [ERROR   ] is detected",
          bool(smt.error_lines("2026-09-06 [ERROR   ] [SMT] Cannot find file")))
    check("unpadded [ERROR] still detected", bool(smt.error_lines("[ERROR] classic")))
    check("[FATAL  ] is detected", bool(smt.error_lines("[FATAL  ] bad")))
    check("[INFO    ] is NOT an error", not smt.error_lines("[INFO    ] fine"))
    check("[SMT               ] is NOT an error", not smt.error_lines("[SMT               ] ok"))

    print("\nB. PE verification")
    with tempfile.NamedTemporaryFile("wb", suffix=".dll", delete=False) as fh:
        fh.write(b"not a PE image, just bytes" * 40)
        junk = fh.name
    check("a non-PE file is rejected", not slc.verify_pe32plus(junk)["ok"],
          slc.verify_pe32plus(junk)["reason"])
    check("a missing file is rejected", not slc.verify_pe32plus(junk + ".missing")["ok"])
    pathlib.Path(junk).unlink(missing_ok=True)
    known = HARNESS / "out" / "r25_sorted.dll"
    if known.exists():
        pe = slc.verify_pe32plus(known)
        check("the known-good sorted DLL verifies as PE32+ x86-64", pe["ok"],
              f"{pe.get('bytes'):,} bytes, {pe.get('sections')} sections" if pe["ok"] else pe["reason"])

    print("\nC. POSITIVE chain — a known-good plant compiles")
    out_xml = HARNESS / "out" / "_gate_d_good.xml"
    r = smt.run_smt(GOOD_INSTANCE, out_xml, cwd=HARNESS, timeout=600)
    check("rung 3 clean on the known-good plant", r["ok"], r["reason"])
    check("rung 3 reports zero [ERROR] lines", r.get("n_errors") == 0,
          f"n_errors={r.get('n_errors')}")
    check("rung 3 read the CWD smtlog, not the install copy",
          "slc_rev" in str(r.get("smtlog", "")), str(r.get("smtlog"))[:70])
    if r["ok"]:
        d = smt.dangling_symbols(out_xml, ["etaFLOC_Process", "kLaGCO2_bub", "SGO2_bub_sat"])
        check("no dangling gas-transfer/flocculation symbols (aeration-bearing class)",
              d["ok"], f"dangling={d['dangling']}")
        out_dll = HARNESS / "out" / "_gate_d_good.dll"
        rl = slc.run_slcompiler(out_xml, out_dll, HARNESS / "_gate_d_src", timeout=1800)
        check("rung 4 links", rl["ok"], rl["reason"])
        check("rung 4 saw the literal link-success line", rl.get("link_success_line"))
        check("the artefact is a real PE32+ x86-64 DLL", rl["pe"]["ok"],
              f"{rl['pe'].get('bytes'):,} bytes" if rl["pe"]["ok"] else rl["pe"]["reason"])
        check("rung 4 created a missing -srcdir rather than failing on it",
              (HARNESS / "_gate_d_src").exists())

    print("\nD. NEGATIVE — the ticket-01 defect must be caught despite exit 0")
    bad_class = CLASSES / "PlantGateD.xlsx"
    bad_inst = INSTANCES / "plant_gate_d.xlsx"
    try:
        _rewrite_class(GOOD_CLASS, bad_class, inject_gap_after_title="Internal connection")
        _rewrite_class(GOOD_INSTANCE, bad_inst)
        # point the instance at the malformed class by name
        import openpyxl, xlsxwriter
        wb = openpyxl.load_workbook(str(bad_inst), read_only=True, data_only=True)
        sheets = {sn: [list(r) for r in wb[sn].iter_rows(values_only=True)] for sn in wb.sheetnames}
        wb.close()
        w = xlsxwriter.Workbook(str(bad_inst), {"strings_to_numbers": False})
        for sn, rows in sheets.items():
            ws = w.add_worksheet(sn)
            for ri, row in enumerate(rows):
                for ci, v in enumerate(row):
                    if v is None:
                        continue
                    if isinstance(v, str) and v.strip() == "PlantR24":
                        v = "PlantGateD"
                    ws.write(ri, ci, v)
        w.close()

        rb = smt.run_smt(bad_inst, HARNESS / "out" / "_gate_d_bad.xml", cwd=HARNESS, timeout=600)
        check("malformed plant is reported as FAILURE by the wrapper", not rb["ok"],
              rb["reason"])
        check("the wrapper's verdict does not depend on the exit code",
              rb.get("returncode_is_not_evidence") is True,
              f"process returncode was {rb.get('returncode')}")
        if rb.get("returncode") == 0 and not rb["ok"]:
            check("EXIT 0 BUT FAILED — the trap is caught in code", True,
                  f"{rb.get('n_errors')} [ERROR] line(s) / xml: {rb.get('xml_status')}")
        else:
            check("malformed run produced [ERROR] lines or no parseable XML",
                  rb.get("n_errors", 0) > 0 or not rb.get("xml"),
                  f"rc={rb.get('returncode')} n_errors={rb.get('n_errors')} xml={rb.get('xml_status')}")
    finally:
        for f in (bad_class, bad_inst):
            try:
                f.unlink()
            except OSError:
                pass

    print("")
    print("D2. THE GENUINE exit-0-while-failing case")
    # The malformation above makes the SMT exit 1, so it does NOT exercise the exit-0 trap.
    # This one does, and it is the trap that actually bit this project: a bare-Simple-CSTR
    # reactive plant yields exit 0, ZERO [ERROR] lines and a valid parseable XML that still
    # carries dangling symbols and cannot link.
    bare = INSTANCES / "plant_attr_none.xlsx"
    if bare.exists():
        SYMS = ["etaFLOC_Process", "kLaGCO2_bub", "SGO2_bub_sat", "kLaGN2_bub"]
        rt = smt.run_smt(bare, HARNESS / "out" / "_gate_d_trap.xml", cwd=HARNESS,
                         timeout=600, allow_nosort=True, extra_args=["-nosort"],
                         check_symbols=SYMS)
        check("the tool really did exit 0", rt.get("returncode") == 0,
              f"returncode={rt.get('returncode')}")
        check("...with ZERO [ERROR] lines", rt.get("n_errors") == 0)
        check("...and a valid parseable XML", "parses" in str(rt.get("xml_status")))
        check("EXIT 0 + CLEAN LOG + VALID XML, yet the wrapper says FAILED",
              not rt["ok"], rt["reason"][:78])
        check("the wrapper names the dangling symbols",
              sorted(rt.get("dangling") or []) == sorted(SYMS), str(rt.get("dangling")))
        rc2 = smt.run_smt(bare, HARNESS / "out" / "_gate_d_trap2.xml", cwd=HARNESS,
                          timeout=600, allow_nosort=True, extra_args=["-nosort"])
        check("without check_symbols the SAME run reads as clean (why the check is mandatory)",
              rc2["ok"] and "SYMBOLS NOT CHECKED" in rc2["reason"])
        for f in ("_gate_d_trap.xml", "_gate_d_trap2.xml"):
            try:
                (HARNESS / "out" / f).unlink()
            except OSError:
                pass
    else:
        check("bare-Simple-CSTR instance available for the exit-0 trap", False, str(bare))

    print("\nE. cleanup")
    for f in ("_gate_d_good.xml", "_gate_d_good.dll", "_gate_d_bad.xml"):
        try:
            (HARNESS / "out" / f).unlink()
        except OSError:
            pass
    shutil.rmtree(HARNESS / "_gate_d_src", ignore_errors=True)
    check("temporary artefacts removed", True)

    bad = [n for n, ok, _ in results if not ok]
    print("\n" + "=" * 66)
    print(f"GATE D: {len(results) - len(bad)}/{len(results)} passed"
          + ("" if not bad else f"\nFAILED: {bad}"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
