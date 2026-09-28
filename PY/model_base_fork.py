"""
model_base_fork.py — Group HH, ticket 12 Phase G2: fork a model base additively (Type B).

Type A adds a new TOPOLOGY over an existing model base. Type B changes the MODEL: new state
variables, new Gujer rows, new stoichiometry. [READ, ticket 04] The unit of change for Type B is
**a forked, renamed, whole model-base workbook** edited additively - Dynamita's own documented
procedure (*SumoSlang for Dummies* Tutorial 2, Technical Reference pp 198-201). There is no
patch or overlay mechanism inside a workbook; the overlay concept exists only at folder level.
**A shipped base is never patched in place.**

WHY THE WRITER IS CHOSEN THE WAY IT IS

  * **openpyxl is disqualified, measured directly rather than inferred.** [MEASURED, ticket 11]
    A no-op `keep_vba=True` round trip of `Sumo2C.xlsm` **drops 32 parts** - `sharedStrings.xml`,
    `calcChain.xml`, 8 drawings, 12 printer settings - rewrites all 37 that remain, and the
    result **fails at the SMT read step with `File error`**. Only `xl/vbaProject.bin` survives.
    It is not importable here and not reachable by a flag.

  * **A fork with no edits is a byte-for-byte COPY, not a re-serialisation.** This is the whole
    point of copy-patch (ticket 11's primary strategy): every part that was not edited stays
    byte-identical *by construction*. Renaming a model base is the common first step and it
    should not risk a single byte.

  * **Row INSERTION goes through Excel COM, and this is not a fallback - it is the correct
    tool for this specific edit.** [READ, ticket 11] The `Sumo2C.xlsm` Help sheet documents
    `MarkName` - **named cells are how symbols resolve**. Inserting rows by rewriting sheet XML
    means renumbering every row below, every `r=` cell reference, `calcChain.xml`, merged-cell
    extents *and* the named ranges. Excel maintains all of those; a hand-rolled XML patcher
    silently would not, and the failure would surface as a symbol resolving to the wrong cell -
    exactly the class of silent wrongness this project keeps finding. COM was validated on a
    macro-bearing `Sumo2C.xlsm`: its SMT XML differs from the pristine baseline by exactly the
    intended change.

  * **Macros are force-disabled during automation.** The vendor workbook carries
    `Create Kinetic Matrix`, `Check Continuity and Rates` and friends. Opening it with macros
    enabled would let workbook code run against a file we are mid-edit on.

THE GATE. A fork is not trusted because this module wrote it. `verify=True` runs rung 2.5
(`model_base_diff`) against the vendor original and returns the **additive-only gate verdict**.
`modified` or `removed` fails: a changed vendor coefficient is the silent result-corrupting
change that ticket 18's calibrated-plant policy exists to prevent.

D:\\SUMO24 IS NOT A DESTINATION HERE. A fork lands in the workspace. Installing it into
`D:\\SUMO24\\Dir\\My Process Code\\Model base\\...` is `hh_install_process_unit`'s job, behind
its own opt-in, and this module refuses an out_path under the install root so the sole-writer
rule stays true.
"""
from __future__ import annotations

import gc
import os
import pathlib
import shutil
import stat
import sys
import time
import zipfile

_HERE = pathlib.Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import model_base_diff

from sumo_paths import installation_path
INSTALL_ROOT = installation_path()
VENDOR_MODEL_BASE = INSTALL_ROOT / "Process code" / "Model base"
# msoAutomationSecurityForceDisable — macros never run while we automate the workbook.
_MSO_FORCE_DISABLE = 3


def shipped_model_bases(root: str | pathlib.Path | None = None) -> set[str]:
    """Every shipped model-base workbook stem (read-only scan)."""
    r = pathlib.Path(root) if root else VENDOR_MODEL_BASE
    if not r.exists():
        return set()
    return {p.stem for p in r.rglob("*.xls[mx]") if not p.name.startswith("~$")}


def _under_install(p: pathlib.Path) -> bool:
    try:
        p.resolve().relative_to(INSTALL_ROOT.resolve())
        return True
    except (ValueError, OSError):
        return False


def verify_parts_preserved(vendor: str | pathlib.Path, fork: str | pathlib.Path) -> dict:
    """Compare the OOXML part lists. This is what catches an openpyxl-shaped loss.

    A fork that dropped `sharedStrings.xml` reads as a perfectly good workbook to most tools
    and is rejected by the SMT with an unhelpful `File error`. Checking the part list catches
    it at fork time instead of three rungs later.
    """
    try:
        with zipfile.ZipFile(str(vendor)) as za, zipfile.ZipFile(str(fork)) as zb:
            a = {i.filename for i in za.infolist()}
            b = {i.filename for i in zb.infolist()}
    except Exception as e:
        return {"ok": False, "reason": "could not read one of the workbooks as OOXML: %s" % e}
    lost = sorted(a - b)
    added = sorted(b - a)
    critical = [p for p in lost if p.endswith(("sharedStrings.xml", "vbaProject.bin"))]
    return {"ok": not critical, "n_vendor_parts": len(a), "n_fork_parts": len(b),
            "lost": lost[:20], "n_lost": len(lost), "added": added[:20],
            "critical_lost": critical,
            "reason": ("critical OOXML parts were lost: " + ", ".join(critical))
                      if critical else "no critical part lost"}


def _make_writable(p: pathlib.Path) -> bool:
    """Clear the read-only attribute a copied vendor file inherits.

    [MEASURED 2026-09-07] `shutil.copy2` copies the source's mode bits, and every shipped model
    base under `D:\SUMO24` is read-only - so a fresh fork lands as `-r--r--r--`. That is a
    silent-failure trap of the exact shape this project keeps finding: Excel would open the
    workbook READ-ONLY without complaint, `DisplayAlerts=False` would swallow the save prompt,
    and `wb.Save()` would leave the file unchanged while the tool reported success. The fork is
    made writable here, and `_apply_additions` additionally ASSERTS `wb.ReadOnly is False`
    rather than trusting that this worked.
    """
    try:
        os.chmod(str(p), os.stat(str(p)).st_mode | stat.S_IWRITE)
        return True
    except OSError:                                          # pragma: no cover
        return False


def _remove(p: pathlib.Path, attempts: int = 5) -> bool:
    """Delete a partial fork, tolerating the read-only bit and a lingering Excel handle."""
    for i in range(attempts):
        try:
            _make_writable(p)
            p.unlink(missing_ok=True)
            return True
        except OSError:
            gc.collect()
            time.sleep(0.4 * (i + 1))
    return not p.exists()


# --------------------------------------------------------------------------- #
# Excel COM — only ever opened on the FORK, never on the vendor original
# --------------------------------------------------------------------------- #

class _Excel:
    """Excel COM session with macros force-disabled and alerts off."""

    def __enter__(self):
        import win32com.client as win32
        self.app = win32.DispatchEx("Excel.Application")
        self.app.Visible = False
        self.app.DisplayAlerts = False
        self.app.AutomationSecurity = _MSO_FORCE_DISABLE
        self.app.AskToUpdateLinks = False
        return self.app

    def __exit__(self, *exc):
        try:
            self.app.Quit()
        except Exception:                                    # pragma: no cover
            pass
        return False


def _header_map(ws, header_row: int, max_col: int = 200) -> dict[str, int]:
    """`{header text: 1-based column}` for one header row, read through COM."""
    out: dict[str, int] = {}
    for c in range(1, max_col + 1):
        v = ws.Cells(header_row, c).Value
        if v is not None and str(v).strip():
            out.setdefault(str(v).strip(), c)
    return out


def _find_block(ws, block_index: int = 0, max_row: int = 4000,
                max_col: int = 200) -> tuple[int, int] | None:
    """Locate the `block_index`-th `Symbol`-headed block. Returns (header_row, last_data_row).

    Blocks repeat down a value sheet: a title row, a header row starting with `Symbol`, then
    data rows until a blank. Headers are found per block because they vary between blocks -
    the same reason `model_base_diff.read_value_sheet` re-reads them.
    """
    seen = -1
    r = 1
    used = int(ws.UsedRange.Rows.Count) + int(ws.UsedRange.Row)
    limit = min(max_row, used + 2)
    while r <= limit:
        row_vals = [ws.Cells(r, c).Value for c in range(1, min(max_col, 40) + 1)]
        texts = [("" if v is None else str(v).strip()) for v in row_vals]
        if "Symbol" in texts:
            seen += 1
            if seen == block_index:
                last = r
                rr = r + 1
                while rr <= limit:
                    vals = [ws.Cells(rr, c).Value for c in range(1, min(max_col, 40) + 1)]
                    if not any(v is not None and str(v).strip() for v in vals):
                        break
                    last = rr
                    rr += 1
                return r, last
        r += 1
    return None


def _append_rows(ws, header_row: int, last_row: int, rows: list[dict]) -> list[int]:
    """Insert `rows` immediately after `last_row`, keyed by header name. Returns row numbers."""
    hdr = _header_map(ws, header_row)
    written = []
    for i, rec in enumerate(rows):
        target = last_row + 1 + i
        ws.Rows(target).Insert()
        for key, val in rec.items():
            col = hdr.get(key)
            if col is None:
                raise KeyError("no column %r in the block header (have: %s)"
                               % (key, sorted(hdr)[:12]))
            ws.Cells(target, col).Value = val
        written.append(target)
    return written


def _apply_additions(fork: pathlib.Path, additions: dict[str, list[dict]],
                     block_index: dict[str, int]) -> dict:
    """Append rows through Excel COM. Isolated so no COM reference outlives this frame.

    An earlier version did the COM work inline in `fork_model_base`. When an edit raised, the
    traceback kept `wb` and `ws` alive, Excel stayed up holding the file, and the cleanup
    `unlink` failed on top of the original error. Everything COM touches is local to this
    function and the error is returned as a STRING, never as an exception carrying frames.
    """
    info: dict = {"rows_added": {}}
    try:
        with _Excel() as app:
            wb = app.Workbooks.Open(str(fork.resolve()), UpdateLinks=0, ReadOnly=False)
            try:
                # Assert rather than assume: a read-only open saves nothing and says nothing.
                if bool(wb.ReadOnly):
                    return {"ok": False, "error": "Excel opened the fork READ-ONLY; a save "
                                                  "would have silently done nothing"}
                names = {ws.Name for ws in wb.Worksheets}
                for sheet, rows in additions.items():
                    if sheet not in names:
                        return {"ok": False,
                                "error": "no sheet %r in the fork (have: %s)"
                                         % (sheet, sorted(names)[:12])}
                    ws = wb.Worksheets(sheet)
                    blk = _find_block(ws, block_index.get(sheet, 0))
                    if blk is None:
                        return {"ok": False,
                                "error": "no Symbol-headed block #%d on sheet %r"
                                         % (block_index.get(sheet, 0), sheet)}
                    header_row, last_row = blk
                    try:
                        written = _append_rows(ws, header_row, last_row, rows)
                    except KeyError as e:
                        return {"ok": False, "error": str(e).strip("\"'")}
                    info["rows_added"][sheet] = {"header_row": header_row,
                                                 "inserted_at": written}
                wb.Save()
                info["saved"] = True
            finally:
                wb.Close(SaveChanges=False)
                wb = None
    except Exception as e:
        return {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}
    finally:
        gc.collect()
    return {"ok": True, **info}


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def fork_model_base(vendor: str | pathlib.Path,
                    out_path: str | pathlib.Path,
                    additions: dict[str, list[dict]] | None = None,
                    block_index: dict[str, int] | None = None,
                    verify: bool = True,
                    overwrite: bool = False) -> dict:
    """Fork a model base to `out_path` and optionally append rows to named sheets.

    `additions` is `{sheet_name: [ {header: value, ...}, ... ]}` - rows appended to the end of
    a `Symbol`-headed block. Only appends: nothing here can edit or delete an existing row, so
    the additive-only gate cannot be failed by this module's own writes. It is still RUN,
    because the point of a gate is not to trust the writer.

    Refusals are return values (tickets 17/19).
    """
    src = pathlib.Path(vendor)
    dst = pathlib.Path(out_path)

    if not src.exists():
        return {"forked": False, "reason": "vendor model base not found: %s" % src}
    if _under_install(dst):
        return {"forked": False,
                "reason": "refusing to write inside %s" % INSTALL_ROOT,
                "detail": ["The install tree has exactly one writer, hh_install_process_unit, "
                           "and it requires an explicit opt-in.",
                           "Fork into the workspace, verify it, then install it."]}
    if dst.exists() and not overwrite:
        return {"forked": False, "reason": "%s already exists" % dst,
                "detail": ["Ticket 15: never overwrite. Fork under a new name, or pass "
                           "overwrite=True deliberately."]}
    if dst.suffix.lower() != src.suffix.lower():
        return {"forked": False,
                "reason": "the fork must keep the vendor extension (%s), got %s"
                          % (src.suffix, dst.suffix),
                "detail": ["An .xlsm carries vbaProject.bin; saving it as .xlsx drops the "
                           "vendor's own macros (Create Kinetic Matrix, Check Continuity "
                           "and Rates)."]}

    shipped = shipped_model_bases()
    if dst.stem in shipped:
        return {"forked": False, "collision": "exact",
                "reason": "fork name %r is IDENTICAL to a shipped model base" % dst.stem,
                "detail": ["Model bases resolve by name; a same-named fork shadows the vendor's "
                           "and nothing reports it (the same first-found-wins mechanism that "
                           "makes ticket 15's unit-name refusal load-bearing).",
                           "Shipped: " + ", ".join(sorted(shipped))]}

    # ---- the copy: byte-identical by construction, vendor opened read-only ----
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(src), str(dst))
    writable = _make_writable(dst)
    parts = verify_parts_preserved(src, dst)
    if not parts["ok"]:                                      # pragma: no cover
        return {"forked": False, "reason": "the copy lost OOXML parts", "parts": parts}

    result: dict = {"forked": True, "vendor": str(src), "fork": str(dst),
                    "model_name": dst.stem, "parts_after_copy": parts,
                    "rows_added": {}, "writer": "copy (byte-identical)",
                    "writable": writable}

    # ---- the edits: Excel COM, on the FORK only ----
    if additions:
        try:
            import win32com.client  # noqa: F401
        except ImportError:
            dst.unlink(missing_ok=True)
            return {"forked": False,
                    "reason": "additive edits need Excel COM (pywin32), which is not available",
                    "detail": ["openpyxl is NOT a fallback: a no-op .xlsm round trip drops 32 "
                               "OOXML parts and the SMT then fails with `File error` "
                               "(measured, ticket 11).",
                               "A fork with no edits does not need COM - omit `additions` to "
                               "get a byte-identical renamed copy."]}
        edit = _apply_additions(dst, additions, block_index or {})
        if not edit["ok"]:
            removed = _remove(dst)
            return {"forked": False,
                    "reason": "the COM edit failed: " + edit["error"],
                    "partial_fork_removed": removed,
                    "detail": ["A half-edited model base is worse than none: rung 2.5 would "
                               "diff it as if it were finished."] +
                              ([] if removed else
                               ["WARNING: the partial fork at %s could NOT be deleted. "
                                "Remove it by hand before forking again." % dst])}
        result["rows_added"] = edit["rows_added"]
        result["writer"] = "copy + Excel COM row insertion"
        result["parts_after_edit"] = verify_parts_preserved(src, dst)

    # ---- the gate: rung 2.5, run even though only appends were possible ----
    if verify:
        try:
            diff = model_base_diff.diff_model_bases(src, dst)
            gate = model_base_diff.additive_only_gate(diff)
            result["diff_summary"] = {k: diff[k] for k in
                                      ("n_added", "n_modified", "n_removed", "sheets_compared")}
            result["additive_only_gate"] = gate
            result["forked"] = bool(gate["ok"])
            if not gate["ok"]:
                result["reason"] = ("the fork FAILED the additive-only gate; it is on disk at "
                                    "%s but must not be used" % dst)
        except Exception as e:
            result["additive_only_gate"] = {
                "ok": None, "reason": "rung 2.5 could not run: %s: %s" % (type(e).__name__, e)}
            result["forked"] = False
            result["reason"] = ("the fork exists but was NOT verified; an unverified Type B "
                                "fork is not usable (ticket 18)")

    result.setdefault("reason", "ok")
    result["next"] = [
        "Point the unit spec's model_binding.model_base at %r." % dst.stem,
        "A NEW STATE VARIABLE forces a recompile AND saved-state re-initialisation: the "
        "compiled model is a closed, ordered symbol table and state.xml is keyed by exact "
        "variable name (ticket 04). A Type B unit goes into a fresh plant, or a calibrated one "
        "only with explicit re-init (hh_add_unit_to_calibrated_plant).",
    ]
    return result


if __name__ == "__main__":                                   # pragma: no cover
    print(__doc__)
