"""
plant_emitter.py — Group HH, ticket 12 Phase G1: emit the test plant a unit compiles inside.

A process unit does not compile on its own. `SMT24.exe` takes a PLANT INSTANCE as its entry
point, walks to the plant CLASS it names, and only then reaches the unit workbook through the
class's `Structure` sheet. [READ, ticket 01: "the SMT will not accept a model base as an entry
point - it derives its search root from the instance position".] So the smallest compilable
artefact around a new unit is a two-file plant, and this module emits it.

    <build_root>/Plant instances/<instance>.xlsx     <- the SMT entry point
    <build_root>/Plant classes/<class>.xlsx          <- names the unit in `Structure`
    <build_root>/Process units/<category>/<unit>/    <- where unit_emitter puts the unit
    <build_root>/{Model base, System files}/         <- empty; the addpath supplies the real ones

FOUR THINGS HERE ARE LOAD-BEARING, each from a measured failure:

  * **No blank row between a block title and its header.** [MEASURED, ticket 01] A single blank
    row between the `Internal connection` title and its `Symbol|Label|From|To` header broke the
    SMT's table scan and blocked the entire round trip. Found by bisection. `_Sheet.block()` in
    `unit_emitter` writes the header on `title_row + 1` unconditionally and is reused here for
    exactly that reason.

  * **xlsxwriter, never openpyxl.** [MEASURED, ticket 01] "openpyxl output is rejected for the
    plant *class* file too, not just instances" - an independent re-confirmation of the 02b
    finding, from a second agent on a different file type.

  * **INVARIANT I7 - a REACTIVE unit must declare its own gas-transfer and flocculation
    symbols.** [MEASURED, tickets 21-24, re-measured here] This module's most useful behaviour
    is refusing. Tickets 21, 22 and 23 spent three rounds hunting for what makes the CLI SMT
    load the model base's `other parameters` sheet, on the premise that the dangling symbols
    lived there. They do not. `Simple CSTR.xlsx` declares **no** flocculation or bubble-transfer
    symbol anywhere; `CSTR with diffused aeration and calculated DO.xlsx` declares
    `etaFLOC,Process` on its `Code` sheet (from `etaFLOC,Process,aer` / `,nonaer` on
    `Parameters`) plus the whole `kLaG.SV,bub` / `SG.SV,bub,sat` / `abub` / `SOTRbub` family.
    Asking an aeration-less unit to run aeration-dependent Gujer rows fails with
    `Variable not found: Sumo__Plant__CSTR__etaFLOC_Process`, and there was never a CLI
    limitation. `check_reactive_precondition()` re-measures this against the actual workbook
    rather than trusting the class name, and emission REFUSES when it fails.

    Note what this means and does not mean: the symbols are per-unit-instance namespaced, so
    adding a *separate* aeration CSTR to the plant does NOT satisfy a bare unit's references.
    The unit under test must declare them itself. An emitter that "fixed" this by bolting an
    extra unit onto the plant would produce a plant that still fails, later and less legibly.

  * **`Reactive` is written explicitly, never left to inherit.** Ticket 01's proof plant carries
    `Reactive=False` as a class-side override; a blank cell inherits, and what it inherits is
    not visible in the file. An explicit cell is the difference between a decision and an
    accident.
"""
from __future__ import annotations

import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

try:
    import xlsxwriter
except ImportError:                                          # pragma: no cover
    xlsxwriter = None

from unit_emitter import _Sheet                              # the title->header invariant

from sumo_paths import installation_path
VENDOR_PU_ROOT = installation_path("Process code", "Process units")
OVERLAY_PU_ROOT = installation_path("Dir", "My Process Code", "Process Units")

# The SMT search root needs these; the last three may be empty (ticket 10).
BUILD_SUBDIRS = ("Plant instances", "Plant classes", "Process units", "Model base",
                 "System files")

H_MODEL_CLASS = ["Symbol", "Name", "Valid", "Invalid", "Rule", "Comments"]
H_PARAMS = ["Symbol", "Name", "Default", "Low limit", "High limit", "Unit", "Decimals",
            "Rule", "Principle/comment"]
H_STRUCTURE = ["Unit component", "Unit name", "Label", "Reactive", "InheritkinPAR",
               "InheritstoPAR", "InheritequPAR", "Models"]
H_INTERNAL = ["Symbol", "Label", "From", "To"]
H_INSTANCE = ["Symbol", "Name", "Class", "Comments"]
H_INST_MODEL = ["Symbol", "Name", "Value", "Rule", "Comments"]
H_INST_DEF = ["Class name", "Instance name", "MODELS", "Connections"]
# The `Unit` sheet of a CLASS opens with a legend row describing the columns (row 2 in the
# vendor `Class template.xlsx` and in ticket 01's compiling plant), then the `Unit` block title.
LEGEND_CLASS_UNIT = ["Connections", "Position", "Reactive", "MODELS", "InheritkinPAR",
                     "InheritstoPAR", "InheritequPAR"]


# --------------------------------------------------------------------------- #
# INVARIANT I7 — the reactive precondition
# --------------------------------------------------------------------------- #

# [MEASURED 2026-09-07 against the shipped library] Symbol stems a reactive Sumo2-family unit
# must declare itself. Greek is normalised because the workbook writes the character and the
# SMT mangles it: `\u03b7FLOC,Process` on the sheet becomes `etaFLOC_Process` in the XML.
AERATION_PROBES: dict[str, tuple[str, ...]] = {
    "flocculation":  ("\u03b7FLOC,Process", "etaFLOC,Process"),
    "bubble_kLa":    ("kLaG.SV,bub", "kLaGO2,bub"),
    "bubble_sat":    ("SG.SV,bub,sat", "SGO2,bub,sat"),
    "specific_area": ("abub",),
}


def declared_symbols(workbook: str | pathlib.Path) -> set[str]:
    """Every symbol a unit workbook declares on `Parameters` / `Code` / `Unit`.

    READ-ONLY, and openpyxl is safe for reading (the ban is on emitting).
    """
    import openpyxl
    wb = openpyxl.load_workbook(str(workbook), read_only=True, data_only=True)
    out: set[str] = set()
    for sn in wb.sheetnames:
        if sn not in ("Parameters", "Code", "Unit"):
            continue
        sym_col = None
        for row in wb[sn].iter_rows(values_only=True):
            cells = [("" if c is None else str(c).strip()) for c in row]
            if not any(cells):
                sym_col = None                     # a blank row ends the block
                continue
            if "Symbol" in cells:
                sym_col = cells.index("Symbol")
                continue
            if sym_col is None or sym_col >= len(cells):
                continue
            s = cells[sym_col]
            if s and s != "Symbol":
                out.add(s)
    wb.close()
    return out


def resolve_unit_class(component: str,
                       build_root: str | pathlib.Path | None = None) -> str | None:
    """Find the workbook a `Structure` row's `Unit component` refers to.

    Search order mirrors the SMT's own: the staged search root first, then the vendor tree,
    then the user overlay. [READ, ticket 10: resolution is search-root-first, then addpath
    roots in command-line order, FIRST-FOUND-WINS.]
    """
    roots: list[pathlib.Path] = []
    if build_root:
        roots.append(pathlib.Path(build_root) / "Process units")
    roots += [VENDOR_PU_ROOT, OVERLAY_PU_ROOT]
    for root in roots:
        if not root.exists():
            continue
        for cand in root.rglob(component + ".xlsx"):
            if not cand.name.startswith("~$"):
                return str(cand)
    return None


def check_reactive_precondition(unit_workbook: str | pathlib.Path) -> dict:
    """INVARIANT I7. Does this unit declare what a reactive Gujer matrix will reference?

    Returns a verdict, never a boolean: which probe families are present, which are missing,
    and what the compile failure will look like if it proceeds anyway.
    """
    try:
        syms = declared_symbols(unit_workbook)
    except Exception as e:
        return {"ok": False, "checked": False,
                "reason": "could not read the unit workbook: %s: %s" % (type(e).__name__, e)}

    present, missing = {}, []
    for family, probes in AERATION_PROBES.items():
        hit = next((p for p in probes for s in syms if p in s), None)
        if hit:
            present[family] = hit
        else:
            missing.append(family)

    if not missing:
        return {"ok": True, "checked": True, "invariant": "I7",
                "reason": "the unit declares gas-transfer and flocculation symbols itself",
                "present": present, "symbols_scanned": len(syms)}
    return {
        "ok": False, "checked": True, "invariant": "I7",
        "reason": "unit declares none of: " + ", ".join(missing) +
                  " - a REACTIVE plant will not compile against it",
        "present": present, "missing": missing, "symbols_scanned": len(syms),
        "detail": [
            "A reactive Gujer matrix references gas-transfer and flocculation symbols that the "
            "unit must declare in its OWN Code sheet. They do NOT come from the model base: "
            "tickets 21-23 assumed they did and spent three rounds on a wrong premise.",
            "Expected failure if emitted anyway: SMT24 reports "
            "`Variable not found: Sumo__Plant__<unit>__etaFLOC_Process` (sorted), or emits XML "
            "with dangling references under -nosort and slcompiler then produces no DLL.",
            "Fixes, in order of preference: (1) name an aeration-bearing class such as "
            "`CSTR with diffused aeration and calculated DO`; (2) add the aeration code block "
            "to the unit spec; (3) emit the plant NON-reactive, which is what ticket 01's "
            "end-to-end proof did.",
            "Adding a separate aeration unit to the plant does NOT help - the symbols are "
            "per-unit-instance namespaced.",
        ],
    }


# --------------------------------------------------------------------------- #
# Emission
# --------------------------------------------------------------------------- #

def _help_sheet(sh: _Sheet, caption: str) -> None:
    sh.cell(1, caption, sh.bold)                 # B2
    sh.ws.write(10, 11, "www.dynamita.com")      # L11, as every shipped template carries


def _emit_plant_class(path: pathlib.Path, units: list[dict], connections: list[dict],
                      model_symbol: str = "MODEL") -> None:
    wb = xlsxwriter.Workbook(str(path), {"strings_to_numbers": False})
    bold = wb.add_format({"bold": True})

    _help_sheet(_Sheet(wb.add_worksheet("Help"), bold), "Template for object classes")

    sh = _Sheet(wb.add_worksheet("Unit"), bold)
    for i, h in enumerate(LEGEND_CLASS_UNIT):    # legend row: C2..I2
        sh.cell(2 + i, h, bold)
    sh.row += 1
    sh.cell(1, "Unit", bold)                     # B3 - the block title
    sh.row += 1
    sh.blank()
    sh.block(H_MODEL_CLASS, [[model_symbol, "Biokinetic model", "", "", "", ""]],
             title="Model", description="Models")

    sh = _Sheet(wb.add_worksheet("Parameters"), bold)
    sh.block(H_PARAMS, [["PAR", "MODEL.PAR.Name", "MODEL.PAR.Default",
                         '"MODEL.PAR.Low limit"', '"MODEL.PAR.High limit"',
                         "MODEL.PAR.Unit", "", "", ""]],
             title="Parameters", title_col=2, description=None)

    sh = _Sheet(wb.add_worksheet("Structure"), bold)
    rows = [[u["component"], u["name"], u.get("label", u["name"]), u.get("reactive", ""),
             True, True, True, model_symbol] for u in units]
    sh.block(H_STRUCTURE, rows, title="Plant", title_col=2, description=None)
    sh.blank()
    sh.block(H_INTERNAL,
             [[c["symbol"], c.get("label", "Liquid"), c["from"], c["to"]] for c in connections],
             title="Internal connection", description="Internal")

    wb.add_worksheet("Code")
    wb.close()


def _emit_plant_instance(path: pathlib.Path, class_name: str, instance_name: str,
                         model: str, model_symbol: str = "MODEL") -> None:
    wb = xlsxwriter.Workbook(str(path), {"strings_to_numbers": False})
    bold = wb.add_format({"bold": True})

    _help_sheet(_Sheet(wb.add_worksheet("Help"), bold), "Template for object instances")

    sh = _Sheet(wb.add_worksheet("Unit"), bold)
    sh.block(H_INSTANCE, [[instance_name, instance_name, class_name, ""]],
             title="Instance", description="Plant instance")
    sh.blank()
    sh.block(H_INST_MODEL, [[model_symbol, "Biokinetic model", model, "", ""]],
             title="Model", description="Biokinetic model")
    sh.blank()
    # The definition block puts its header in column C, not B.
    sh.block(H_INST_DEF, [[class_name, instance_name, model, ""]],
             title="Instance", description="Plant instance definition", start_col=2)

    sh = _Sheet(wb.add_worksheet("Parameters"), bold)
    sh.block(H_PARAMS, [], title="Parameters", title_col=2, description=None)

    wb.add_worksheet("Code")
    wb.close()


def emit_test_plant(unit_component: str,
                    build_root: str | pathlib.Path,
                    unit_label: str = "CSTR",
                    model: str = "Sumo2C",
                    reactive: bool = False,
                    class_name: str = "Plant",
                    instance_name: str | None = None,
                    instance_symbol: str | None = None,
                    unit_class_path: str | None = None,
                    allow_unverified_reactive: bool = False) -> dict:
    """Emit the plant class + instance that make `unit_component` compilable.

    Refusals are return values (tickets 17/19). The reactive precondition (I7) is checked
    against the unit's actual workbook, not against its name.
    """
    if xlsxwriter is None:
        return {"emitted": False, "reason": "xlsxwriter not installed",
                "detail": ["openpyxl is BANNED as an emitter - the SMT rejects its output for "
                           "the plant CLASS file too, not only for unit workbooks (ticket 01)"]}
    if not (unit_component or "").strip():
        return {"emitted": False, "reason": "a unit component name is required"}

    root = pathlib.Path(build_root)
    resolved = unit_class_path or resolve_unit_class(unit_component, root)

    precondition = None
    if reactive:
        if not resolved:
            if not allow_unverified_reactive:
                return {"emitted": False,
                        "reason": "reactive plant requested but the unit workbook for %r could "
                                  "not be found, so invariant I7 cannot be checked"
                                  % unit_component,
                        "detail": ["Emit the unit first (hh_emit_unit_workbook), or pass "
                                   "unit_class_path.",
                                   "allow_unverified_reactive=True proceeds without the check "
                                   "and accepts a likely `Variable not found` compile failure."],
                        "searched": [str(root / "Process units"), str(VENDOR_PU_ROOT),
                                     str(OVERLAY_PU_ROOT)]}
            precondition = {"ok": None, "checked": False,
                            "reason": "unit workbook not found; check skipped by explicit opt-in"}
        else:
            precondition = check_reactive_precondition(resolved)
            if not precondition["ok"] and not allow_unverified_reactive:
                return {"emitted": False, "reason": "invariant I7: " + precondition["reason"],
                        "unit_workbook": resolved, "precondition": precondition}

    for sub in BUILD_SUBDIRS:
        (root / sub).mkdir(parents=True, exist_ok=True)

    inst = instance_name or class_name
    # [MEASURED] The instance SYMBOL becomes the compiled variable namespace: ticket 01's
    # plant produced `Sumo__Plant__CSTR__*`, and every downstream reference in this project
    # (rung 5's tracer probes, the map's symbol tables) is written against `Sumo__Plant__`.
    # It is deliberately NOT tied to the filename - ticket 01's instance file was named
    # `hh_cstr_v1.xlsx` while its symbol was `Plant`. Renaming the symbol renames every
    # variable in the DLL, so it defaults to the class name and changes only when asked.
    sym = instance_symbol or class_name
    # `Reactive` is written explicitly, never left blank to inherit an invisible default.
    units = [{"component": "State influent", "name": "Influent", "label": "Influent",
              "reactive": ""},
             {"component": unit_component, "name": unit_label, "label": unit_label,
              "reactive": bool(reactive)}]
    connections = [{"symbol": "Inflpipe", "label": "Liquid",
                    "from": "Influent..outp", "to": unit_label + "..inp"}]

    class_path = root / "Plant classes" / (class_name + ".xlsx")
    inst_path = root / "Plant instances" / (inst + ".xlsx")
    _emit_plant_class(class_path, units, connections)
    _emit_plant_instance(inst_path, class_name, sym, model)

    gap = verify_plant_workbook(class_path)
    if not gap.get("ok", True):
        return {"emitted": False, "reason": "emitted class violates the title/header invariant",
                "detail": gap.get("faults", []), "class_workbook": str(class_path)}

    return {
        "emitted": True, "reason": "ok",
        "class_workbook": str(class_path), "instance_workbook": str(inst_path),
        "smt_entry_point": str(inst_path), "build_root": str(root),
        "instance_symbol": sym,
        "variable_namespace": "Sumo__%s__%s__*" % (sym, unit_label),
        "unit_workbook": resolved,
        "reactive": bool(reactive), "precondition": precondition,
        "structure_verified": gap,
        "next": ['hh_compile_smt(instance="%s", cwd="%s") - the CWD must be the build root, '
                 'because SMT24 writes smtlog.txt into the invocation CWD.' % (inst_path, root),
                 "Never pass -nosort: it emits unordered algebra that silently never evaluates."],
    }


def verify_plant_workbook(xlsx_path: str | pathlib.Path) -> dict:
    """Re-read an emitted plant workbook and assert the ticket-01 title->header adjacency.

    Reads the file back rather than trusting the writer - the same rule `unit_emitter` follows,
    for the same reason: the defect this catches cost ticket 01 its entire round trip.
    """
    try:
        import openpyxl
    except ImportError:                                      # pragma: no cover
        return {"ok": None, "reason": "openpyxl unavailable for verification"}

    titles = {"Model", "Plant", "Instance", "Internal connection", "Parameters"}
    wb = openpyxl.load_workbook(str(xlsx_path), read_only=True, data_only=True)
    faults, blocks = [], 0
    for sn in wb.sheetnames:
        rows = [[("" if c is None else str(c).strip()) for c in r]
                for r in wb[sn].iter_rows(max_col=12, values_only=True)]
        for i, r in enumerate(rows):
            cell_b = r[1] if len(r) > 1 else ""
            cell_c = r[2] if len(r) > 2 else ""
            # A title cell sits in B (or C on `Parameters`/`Structure`) and is followed by a
            # header row. The empty `Unit` block on a class sheet carries no table and is
            # deliberately not in `titles`.
            if cell_b not in titles and cell_c not in titles:
                continue
            nxt = rows[i + 1] if i + 1 < len(rows) else []
            blocks += 1
            if not any(nxt):
                faults.append("%s row %d: BLANK ROW between title and header - this is the "
                              "ticket-01 defect" % (sn, i + 1))
            elif not any(h in nxt for h in ("Symbol", "Unit component", "Class name")):
                faults.append("%s row %d: next row is not a recognised header: %s"
                              % (sn, i + 1, nxt[:5]))
    wb.close()
    return {"ok": not faults, "blocks_checked": blocks, "faults": faults}


if __name__ == "__main__":                                   # pragma: no cover
    print(__doc__)
