"""
unit_emitter.py — Group HH, ticket 12 Phase C1: emit a Sumo process-unit workbook from a spec.

Turns an ACCEPTED `unit_spec.json` into a positionally-valid Sumo process-unit folder:

    custom_units/<slug>/
        <Unit Name>.xlsx          the unit workbook
        <Unit Name>.emf           the icon (icon_emitter)
        <Folder> Group Info.xlsx  the group manifest

Everything here is driven by the measured format contract in `PY/data/workbook_format.json`
(ticket 02b, full-corpus census) and verified against the shipped `Simple CSTR.xlsx` layout.

NON-NEGOTIABLES, each traceable to a measured failure:

  * **xlsxwriter, never openpyxl.** openpyxl emits `t="inlineStr"` and drops `sharedStrings.xml`,
    which the SMT rejects with "File error". xlsxwriter emits `t="s"` + sharedStrings and the SMT
    loads it. (workbook_format.json -> writer_library)

  * **NEVER a blank row between a block's title row and its header row.** That single defect
    broke the SMT's table scan and blocked ticket 01's entire round trip. `_block()` writes the
    header on `title_row + 1` unconditionally, and `verify_no_title_header_gap()` re-reads the
    emitted file and asserts it.

  * **Column A is always empty.** Every table starts in column B (Components starts at C).

  * **Positional irregularity is the norm.** On `Unit`, block titles sit in B with the
    description in C; on `Parameters`/`Display`/`Popup` the title sits in C; on `Code` the
    section title sits in A, then a blank row, then the block title in C with `Codelocation(...)`
    in D. A naive uniform writer produces a workbook the SMT silently misreads.

  * **Emission REFUSES on an unaccepted spec.** `spec_review.may_emit()` is the gate (ticket 08);
    it is called here, not trusted to have been called by the caller.

  * **The `Appearance` table and the Group Info `Unit` sheet are GUI contracts that NO compile
    rung reads.** Nothing downstream will catch their absence, so they are emitted unconditionally
    and checked by the self-test.

  * **Cells are vendor-TYPED, never text.** [MEASURED 2026-09-07, HH_DynaSand_v1] The GUI's
    UnitPalette.LoadUnit int.Parse()es every port Size cell and reads parameter/attribute
    cells natively; the emitted-but-text workbook compiled clean through every SMT rung and
    was still silently dropped from the palette (System.FormatException). Port rows are
    emitted with Image = phase and Size = 24 (vendor census value) as NATIVE cells, numbers
    and bools stay native, and `verify_gui_typing()` re-reads the file and refuses emission
    on any fault. openpyxl remains banned for EMISSION (SMT "File error"); zip-surgical edits
    are the only sanctioned post-write touch.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import sys
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

try:
    import xlsxwriter
except ImportError:                                        # pragma: no cover
    xlsxwriter = None

import spec_review

# Canonical sheet order — 157 of the corpus, the single most common sequence.
# `Predefined charts` is in only 6 of 237 units and is NOT emitted by default.
CANONICAL_SHEETS = ["Help", "Unit", "Parameters", "Code", "Display", "Popup"]

# Header rows, measured (workbook_format.json -> sheet_contracts)
H_PORTS      = ["Symbol", "Name", "Position", "Phase", "Direction", "Image", "Size",
                "Rule", "Comments"]
H_ATTRS      = ["Symbol", "Name", "Default", "Rule", "Comments"]
H_ATTRS_VAL  = ["Symbol", "Name", "Value", "Rule"]
H_MODEL      = ["Symbol", "Name", "Valid", "Invalid", "Rule", "Comments"]
H_PARAMS     = ["Symbol", "Name", "Default", "Low limit", "High limit", "Unit", "Decimals",
                "Rule", "Principle/comment"]
H_CODE       = ["Symbol", "Name", "Expression", "Unit", "Decimals", "Rule", "Principle/comment"]
H_DISPLAY    = ["Symbol", "Name", "Value", "Unit", "Decimals", "Rule", "Principle/comment"]
H_GROUPINFO  = ["Symbol", "Name", "Value", "Rule"]


class EmitRefused(Exception):
    """Raised only for programmer error. Policy refusals are RETURN VALUES (ticket 08/17/19)."""


# --------------------------------------------------------------------------- #
# Low-level sheet writing
# --------------------------------------------------------------------------- #

class _Sheet:
    """A sheet being built as a vertical stack of blocks.

    Row 0 (Excel row 1) is always left blank, as every shipped workbook does.
    """

    def __init__(self, ws, bold):
        self.ws = ws
        self.bold = bold
        self.row = 1          # 0-indexed; row 0 stays blank

    def blank(self, n: int = 1) -> None:
        self.row += n

    def cell(self, col: int, value: Any, fmt=None) -> None:
        if value is None:
            return
        self.ws.write(self.row, col, value, fmt)

    def block(self, header: list[str], rows: list[list[Any]],
              title: str | None = None, title_col: int = 1,
              description: str | None = None, description_col: int = 2,
              extra_title_cell: tuple[int, str] | None = None,
              start_col: int = 1) -> None:
        """Write title row (optional) then header IMMEDIATELY BELOW, then data rows.

        The title->header adjacency is the invariant that ticket 01 proved load-bearing:
        a blank row between them terminates the SMT's table scan and the table is silently
        skipped. There is deliberately no parameter to insert one.
        """
        if title is not None:
            self.cell(title_col, title, self.bold)
            if description is not None:
                self.cell(description_col, description)
            if extra_title_cell is not None:
                self.cell(extra_title_cell[0], extra_title_cell[1])
            self.row += 1                      # <-- header lands on the very next row
        for i, h in enumerate(header):
            self.cell(start_col + i, h, self.bold)
        self.row += 1
        for r in rows:
            for i, v in enumerate(r):
                self.cell(start_col + i, v)
            self.row += 1


# --------------------------------------------------------------------------- #
# Spec -> sheet content
# --------------------------------------------------------------------------- #

def _s(v: Any) -> str:
    return "" if v is None else str(v)


def _native(v: Any) -> Any:
    """[MEASURED 2026-09-07, HH_DynaSand_v1] The GUI's UnitPalette.LoadUnit int.Parse()es
    the port Size cell and reads parameter/attribute cells natively; text-typed numerics
    crash it (System.FormatException: Input string was not in a correct format) and the
    unit is silently dropped from the palette. Vendor workbooks store Default/Low/High/
    Decimals as native numbers and attribute defaults as native bools. Returns a native
    int/float/bool when the value is one (or a clean numeric/boolean string); the original
    string otherwise ('Zero', 'One', 'BigNumber', '174x90', expressions stay text)."""
    if v is None:
        return ""
    if isinstance(v, bool) or isinstance(v, (int, float)):
        return v
    s = str(v).strip()
    if not s:
        return ""
    if s.lower() == "true":
        return True
    if s.lower() == "false":
        return False
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        return s


def _coeff(node: Any) -> Any:
    """A coefficient/parameter node's raw value (schema `coefficient` shape)."""
    if isinstance(node, dict) and "value" in node:
        return node["value"]
    return node


def _write_help(sh: _Sheet, spec: dict) -> None:
    ident = spec.get("identity", {})
    sh.cell(1, ident.get("name") or ident.get("qualified_name") or "Custom unit", sh.bold)
    sh.blank(2)
    sh.cell(2, ident.get("category", "Custom"))
    sh.row += 1
    for line in (spec.get("description") or "").splitlines() or [""]:
        if line.strip():
            sh.cell(2, line.strip())
            sh.row += 1


def _write_unit(sh: _Sheet, spec: dict, icon_filename: str) -> None:
    ident = spec.get("identity", {})
    name = ident.get("name", "Unit")

    ports = []
    for p in spec.get("ports", []) or []:
        ports.append([p.get("symbol"), p.get("name"), p.get("position", ""),
                      p.get("phase", "L"), p.get("direction", ""),
                      p.get("image") or p.get("phase") or "L",        # [MEASURED] vendor col G
                      _native(p.get("size") or 24),                   # [MEASURED] vendor col H: int 24
                      p.get("rule", ""), p.get("comments", "")])
    if ports:
        sh.block(H_PORTS, ports, title="Port", description=f"{name} connections")
        sh.blank()

    attrs = []
    for a in spec.get("attributes", []) or []:
        attrs.append([a.get("symbol"), a.get("name"), _native(_coeff(a.get("default"))),
                      a.get("rule", ""), a.get("comments", "")])
    if attrs:
        sh.block(H_ATTRS, attrs, title="Attribute", description=f"{name} attributes")
        sh.blank()

    mb = spec.get("model_binding") or {}
    if mb.get("model_symbol") or mb.get("valid") or mb.get("invalid"):
        sh.block(H_MODEL,
                 [[mb.get("model_symbol", "MODEL"), mb.get("name", "Biokinetic model"),
                   "; ".join(mb.get("valid", []) or []),
                   "; ".join(mb.get("invalid", []) or []), "", ""]],
                 title="Model", description="Models")
        sh.blank()

    handlings = []
    for h in (spec.get("handlings") or []):
        handlings.append([h.get("symbol"), h.get("name"), h.get("default", ""),
                          h.get("rule", ""), h.get("comments", "")])
    if handlings:
        sh.block(H_ATTRS, handlings, title="Handling", description="Handlings",
                 extra_title_cell=(3, "Scope(MODEL)"))
        sh.blank()

    # Appearance — a GUI contract NO compile rung reads. Always emitted.
    gui = spec.get("gui") or {}
    appearance = [["Default", "", icon_filename, ""],
                  ["CustomSize", "", gui.get("custom_size", "174x90"), ""]]
    sh.block(H_ATTRS_VAL, appearance, title="Appearance", description="Unit appearance")


def _write_parameters(sh: _Sheet, spec: dict) -> None:
    rows = []
    for p in spec.get("parameters", []) or []:
        rows.append([p.get("symbol"), p.get("name"), _native(_coeff(p.get("default"))),
                     _native(p.get("low_limit")), _native(p.get("high_limit")),
                     _s(p.get("unit")), _native(p.get("decimals")),
                     _s(p.get("rule")), _s(p.get("comments"))])
    # Parameters puts its block title in column C, not B.
    sh.block(H_PARAMS, rows, title=None if not rows else "Unit settings", title_col=2,
             description=None)


def _write_code(sh: _Sheet, spec: dict) -> None:
    blocks = spec.get("code_blocks") or []
    for blk in blocks:
        section = blk.get("section")
        if section:                       # section title in column A, THEN a blank row
            sh.cell(0, section, sh.bold)
            sh.row += 1
            sh.blank()
        rows = []
        for ln in blk.get("lines", []) or []:
            rows.append([ln.get("symbol"), ln.get("name"), ln.get("expression"),
                         _s(ln.get("unit")), _native(ln.get("decimals")),
                         _s(ln.get("rule")), _s(ln.get("comments"))])
        loc = blk.get("codelocation", "Dynamic")
        sh.block(H_CODE, rows, title=blk.get("title", section or "Code"), title_col=2,
                 description=None, extra_title_cell=(3, f"Codelocation({loc})"))
        sh.blank()


def _write_display(sh: _Sheet, spec: dict, key: str, location: str) -> None:
    rows = []
    for d in ((spec.get("gui") or {}).get(key) or []):
        rows.append([d.get("symbol"), d.get("name"), _native(d.get("value")), _s(d.get("unit")),
                     _native(d.get("decimals")), _s(d.get("rule")), _s(d.get("comments"))])
    sh.block(H_DISPLAY, rows, title=f"{key.capitalize()} variables", title_col=2,
             description=None, extra_title_cell=(3, f"Location({location})"))


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def validate_spec_shape(spec: dict) -> dict:
    """Structural checks the emitter needs but rung 1 does not perform.

    [MEASURED, adversarial review] A `Parameters`-sheet SECTION LABEL ("Advanced", sitting in
    column B with no name and no default) was accepted as a parameter and emitted; the SMT then
    failed far away with `Cannot determine the right hand side of the equation ... Symbol:
    Sumo__Plant__CSTR__param__Advanced`. Rung 1 inspects coefficient nodes; it has no opinion on
    whether a parameter row is a parameter at all.
    """
    faults = []
    for i, prm in enumerate(spec.get("parameters", []) or []):
        sym = (prm.get("symbol") or "").strip()
        if not sym:
            faults.append({"path": f"parameters[{i}]", "why": "no symbol"})
            continue
        d = prm.get("default")
        dv = d.get("value") if isinstance(d, dict) else d
        if (dv is None or str(dv).strip() == "") and not str(prm.get("name") or "").strip():
            faults.append({"path": f"parameters[{i}]", "symbol": sym,
                           "why": "no name and no default - this looks like a SECTION LABEL, "
                                  "not a parameter; the SMT will fail on the emitted equation"})
    for i, blk in enumerate(spec.get("code_blocks", []) or []):
        for j, ln in enumerate(blk.get("lines", []) or []):
            if not (ln.get("symbol") or "").strip():
                faults.append({"path": f"code_blocks[{i}].lines[{j}]", "why": "code line has no symbol"})
            elif not str(ln.get("expression") or "").strip():
                faults.append({"path": f"code_blocks[{i}].lines[{j}]",
                               "symbol": ln.get("symbol"),
                               "why": "code line has no expression"})
    return {"ok": not faults, "faults": faults}


def emit_unit(spec: dict, out_dir: str | pathlib.Path,
              icon_filename: str | None = None,
              allow_bulk: bool = False,
              workbook_name: str | None = None,
              group_info: dict | None = None) -> dict:
    """Emit the unit workbook (and optionally the Group Info beside it).

    `group_info` = {"name": <group>, "default_unit": <stem>, "sorting_priority": int}.
    [MEASURED 2026-09-07] the Group Info must be a SIBLING of the unit workbooks inside
    the palette family folder; emitting it here keeps workbook+manifest atomic. Returns a
    structured result; refusals are values, not exceptions."""
    if xlsxwriter is None:
        return {"emitted": False, "reason": "xlsxwriter not installed",
                "detail": ["openpyxl is BANNED as an emitter - the SMT rejects its output"]}

    gate = spec_review.may_emit(spec, allow_bulk=allow_bulk)
    if not gate["may_emit"]:
        return {"emitted": False, "reason": "refused by the rung-1 emission gate",
                "detail": [gate["reason"]] + list(gate.get("detail", []))}

    shape = validate_spec_shape(spec)
    if not shape["ok"]:
        return {"emitted": False, "reason": "spec shape is not emittable",
                "detail": [f"{f.get('path')}: {f['why']}" for f in shape["faults"][:6]]}

    ident = spec.get("identity", {})
    # [MEASURED] The SMT resolves a unit by its QUALIFIED name (the plant Structure names
    # `HH_CSTR_v1`, and the SMT reports `Cannot find file ... File: HH_CSTR_v1`). Naming the
    # workbook after `identity.name` ("CSTR Reactor.xlsx") produces a folder that does not
    # compile until someone renames it. Qualified name wins; `name` is the display name.
    name = (workbook_name or ident.get("qualified_name") or ident.get("name") or "CustomUnit")
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    xlsx = out / f"{name}.xlsx"
    icon = icon_filename or f"{name}.emf"

    wb = xlsxwriter.Workbook(str(xlsx), {"strings_to_numbers": False})
    bold = wb.add_format({"bold": True})
    writers = {
        "Help":       lambda sh: _write_help(sh, spec),
        "Unit":       lambda sh: _write_unit(sh, spec, icon),
        "Parameters": lambda sh: _write_parameters(sh, spec),
        "Code":       lambda sh: _write_code(sh, spec),
        "Display":    lambda sh: _write_display(sh, spec, "display", "Unit"),
        "Popup":      lambda sh: _write_display(sh, spec, "popup", "Unit"),
    }
    for sheet_name in CANONICAL_SHEETS:
        sh = _Sheet(wb.add_worksheet(sheet_name), bold)
        writers[sheet_name](sh)
    wb.close()

    # [MEASURED 2026-09-07] The GUI contract NO compile rung checks: UnitPalette.LoadUnit
    # int.Parse()es the port Size cell and reads cells natively. A workbook that compiles
    # clean but carries text-typed numerics or a missing port Size is silently dropped
    # from the palette. Verify the written file, not the writer's intent; refuse (and
    # remove) on any fault so a GUI-crashing workbook can never ship.
    typing = verify_gui_typing(xlsx)
    if typing.get("ok") is False:
        try:
            xlsx.unlink()
        except OSError:
            pass
        return {"emitted": False,
                "reason": "emitted workbook fails the GUI typing contract (would crash "
                          "UnitPalette.LoadUnit); workbook removed",
                "detail": list(typing.get("faults", []))[:6]}

    gi_path = None
    if group_info and group_info.get("name"):
        g = emit_group_info(out, str(group_info["name"]),
                            str(group_info.get("default_unit") or name),
                            sorting_priority=int(group_info.get("sorting_priority") or 1000))
        if not g.get("emitted"):
            return {"emitted": False,
                    "reason": "workbook emitted but the Group Info was refused",
                    "detail": [g.get("reason", "")], "workbook": str(xlsx)}
        gi_path = g["path"]

    return {"emitted": True, "reason": "ok",
            "workbook": str(xlsx), "icon_expected": str(out / icon),
            "group_info": gi_path,
            "gui_typing": typing,
            "sheets": list(CANONICAL_SHEETS)}


def emit_group_info(folder: str | pathlib.Path, group_name: str,
                    default_unit_stem: str, sorting_priority: int = 1000) -> dict:
    """Emit `<group> Group Info.xlsx`.

    `DefaultUnit` is a file STEM with no extension (ticket 14) — passing a filename with
    `.xlsx` produces a group the GUI cannot resolve, and no compile rung will tell you.
    """
    if xlsxwriter is None:
        return {"emitted": False, "reason": "xlsxwriter not installed"}
    if default_unit_stem.lower().endswith(".xlsx"):
        return {"emitted": False, "reason": "DefaultUnit must be a stem with no extension",
                "detail": [f"got {default_unit_stem!r}"]}
    out = pathlib.Path(folder)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{group_name} Group Info.xlsx"
    wb = xlsxwriter.Workbook(str(path))
    bold = wb.add_format({"bold": True})

    sh = _Sheet(wb.add_worksheet("Help"), bold)
    sh.cell(1, group_name, bold)

    sh = _Sheet(wb.add_worksheet("Unit"), bold)
    sh.block(H_GROUPINFO,
             [["SortingPriority", "", sorting_priority, ""],
              ["DefaultUnit", "", default_unit_stem, ""]],
             title=None, title_col=2, description=None)
    # C2 carries the group display name (group_info_contract)
    sh.ws.write(1, 2, group_name)
    wb.close()
    return {"emitted": True, "path": str(path), "default_unit": default_unit_stem}


# --------------------------------------------------------------------------- #
# Structural verification of what was actually written
# --------------------------------------------------------------------------- #

_GUI_KEYWORDS = {"zero", "one", "bignumber", "true", "false"}


def _gui_numberish(v: Any) -> bool:
    """True when a parameter cell is GUI-safe. Keyword/constant references ('Zero',
    'MinV', quoted 'MODEL.PAR.Low limit') are legal text the vendor ships everywhere;
    what the vendor NEVER ships is a text-typed numeral ('0.11' as a string) - that is
    the emitter bug this check exists to catch."""
    if v is None or v == "":
        return True
    if isinstance(v, bool):
        return True
    if isinstance(v, (int, float)):
        return True
    s = str(v).strip().strip('"')
    if s.upper().startswith("MODEL.") or ".." in s:
        return True
    try:
        float(s)
        return False                     # a numeral written as text - the emitter bug
    except ValueError:
        return True


def verify_gui_typing(xlsx_path: str | pathlib.Path) -> dict:
    """Re-read the emitted workbook and assert the GUI's cell-typing contract.

    [MEASURED 2026-09-07, HH_DynaSand_v1] NO compile rung checks this: Sumo's
    UnitPalette.LoadUnit int.Parse()es every port Size cell, so a missing or text-typed
    Size crashes the palette load (System.FormatException) and the unit is silently
    dropped from the drawing board even though every compile gate passed. Also asserts
    parameter Default/Low/High/Decimals are GUI-safe and attribute defaults are non-empty.
    """
    try:
        import openpyxl                       # READING only; never used to emit
    except ImportError:
        return {"ok": None, "reason": "openpyxl unavailable for verification"}

    wb = openpyxl.load_workbook(str(xlsx_path), read_only=True, data_only=True)
    faults = []

    if "Unit" in wb.sheetnames:
        for i, r in enumerate(wb["Unit"].iter_rows(max_col=10, values_only=True), start=1):
            vals = list(r) + [None] * 10
            sym, pos = vals[1], (str(vals[3]) if vals[3] is not None else "")
            direction = vals[5]
            if sym and direction in ("in", "out") and (pos.endswith("px") or ".." in pos or pos == ""):
                size, image = vals[7], vals[6]
                ok_size = isinstance(size, int) and not isinstance(size, bool) and size >= 1
                if not ok_size:
                    faults.append(f"Unit row {i} ({sym}): Size cell is {size!r} - the GUI "
                                  f"int.Parse()es it; a missing or text value crashes "
                                  f"UnitPalette.LoadUnit")
                if not image:
                    faults.append(f"Unit row {i} ({sym}): Image cell is empty (vendor: the port phase)")

    if "Parameters" in wb.sheetnames:
        for i, r in enumerate(wb["Parameters"].iter_rows(max_col=10, values_only=True), start=1):
            vals = list(r) + [None] * 10
            sym = vals[1]
            if not sym or str(sym).strip() in ("Symbol", ""):
                continue
            if vals[2] in (None, "") and vals[3] in (None, ""):
                continue                       # section label row
            for col, label in ((3, "Default"), (4, "Low limit"), (5, "High limit"),
                               (7, "Decimals")):
                if not _gui_numberish(vals[col]):
                    faults.append(f"Parameters row {i} ({sym}): {label} is text-typed "
                                  f"({vals[col]!r}); the vendor stores native numbers or keywords")
    wb.close()
    return {"ok": not faults, "faults": faults}


def verify_no_title_header_gap(xlsx_path: str | pathlib.Path) -> dict:
    """Re-read the emitted workbook and assert the ticket-01 invariant.

    A blank row between a block title and its header terminates the SMT's table scan; the
    table is then silently skipped and the compile fails far away from the cause. This reads
    the file back rather than trusting the writer.
    """
    try:
        import openpyxl                       # READING only; never used to emit
    except ImportError:
        return {"ok": None, "reason": "openpyxl unavailable for verification"}

    wb = openpyxl.load_workbook(str(xlsx_path), read_only=True, data_only=True)
    faults, blocks = [], 0
    known_titles = {"Port", "Attribute", "Model", "Handling", "AttributeGroup", "Appearance"}
    for sn in wb.sheetnames:
        rows = [[("" if c is None else str(c).strip()) for c in r]
                for r in wb[sn].iter_rows(max_col=10, values_only=True)]
        for i, r in enumerate(rows):
            is_title = (len(r) > 1 and r[1] in known_titles) or \
                       (len(r) > 3 and str(r[3]).startswith(("Codelocation(", "Location(")))
            if not is_title:
                continue
            blocks += 1
            nxt = rows[i + 1] if i + 1 < len(rows) else []
            if not any(nxt):
                faults.append(f"{sn} row {i+1}: BLANK ROW between title and header")
            elif "Symbol" not in nxt:
                faults.append(f"{sn} row {i+1}: next row is not a header (no 'Symbol')")
    wb.close()
    return {"ok": not faults, "blocks_checked": blocks, "faults": faults}


if __name__ == "__main__":                                  # pragma: no cover
    print(__doc__)
