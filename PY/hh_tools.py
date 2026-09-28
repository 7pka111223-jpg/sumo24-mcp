"""
hh_tools.py — Group HH, ticket 12 Phase F: the MCP surface for SumoSlang unit authoring.

24 tools (ticket 09 inventory, user-confirmed count). This module holds the TOOL DEFINITIONS and
the DISPATCH; the work itself lives in the rung modules built in Phases B2/C/D/E:

    rung 1    spec_review.py        rung 2.5  model_base_diff.py    emitter  unit_emitter.py
    rung 1.5  dimension_checker.py  rung 3    smt_runner.py         icons    icon_emitter.py
    rung 2    continuity_checker.py rung 4    slc_runner.py         naming   sumoslang_author.py
                                    rung 5    tracer_test.py

WHY A SEPARATE MODULE. Ticket 09's first draft said "one new module `sumoslang_author.py` holds
all logic" — but that file ALREADY EXISTS and holds ticket 16's cleanup/rollback surface. Piling
the MCP layer into it risks the exact overwrite that correction was written to prevent, so the
MCP surface lives here and imports it.

TWO RULES THIS MODULE ENFORCES:

  * **Refusals are structured return values, never exceptions** (tickets 17/19). Every entry
    point returns a dict; nothing raises across the MCP boundary.

  * **A tool that is not built says so.** `_not_implemented()` exists for exactly that and is
    deliberately kept even though nothing uses it now: registering a tool that pretends to work
    is the asserted-but-absent failure this project kept finding, and the next tool added here
    should refuse loudly before it refuses quietly.

    [2026-09-07] All 24 are now implemented. The last six landed in Phase G/H:
    `spec_builder.py` (the prose front door, the structured back door, structured editing),
    `plant_emitter.py` (test-plant emission), `model_base_fork.py` (the Type B fork) and
    `unit_installer.py` (install - the only writer into D:\SUMO24).
"""
from __future__ import annotations

import json
import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

_IMPORT_ERRORS: dict[str, str] = {}


def _try(name):
    try:
        return __import__(name)
    except Exception as e:                                   # pragma: no cover
        _IMPORT_ERRORS[name] = repr(e)
        return None


spec_review = _try("spec_review")
dimension_checker = _try("dimension_checker")
continuity_checker = _try("continuity_checker")
model_base_diff = _try("model_base_diff")
smt_runner = _try("smt_runner")
slc_runner = _try("slc_runner")
tracer_test = _try("tracer_test")
unit_emitter = _try("unit_emitter")
icon_emitter = _try("icon_emitter")
sumoslang_author = _try("sumoslang_author")
spec_builder = _try("spec_builder")
plant_emitter = _try("plant_emitter")
model_base_fork = _try("model_base_fork")
unit_installer = _try("unit_installer")

S = {"type": "string"}
B = {"type": "boolean"}
N = {"type": "number"}
ARR = {"type": "array", "items": {"type": "string"}}


def _schema(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or []}


def _load_spec(path: str) -> tuple[dict | None, dict | None]:
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8")), None
    except Exception as e:
        return None, {"ok": False, "error": f"could not read spec {path!r}: {e}"}


def _unavailable(module: str) -> dict:
    return {"ok": False, "error": f"module {module} unavailable",
            "detail": [_IMPORT_ERRORS.get(module, "not imported")]}


def _not_implemented(tool: str, phase: str, what: str) -> dict:
    return {"ok": False, "not_implemented": True, "tool": tool,
            "reason": f"{tool} is registered but NOT built yet",
            "detail": [what, f"Scheduled in ticket 12 {phase}.",
                       "This tool refuses rather than returning a plausible-looking result."]}


# --------------------------------------------------------------------------- #
# Tool definitions — (name, description, inputSchema)
# --------------------------------------------------------------------------- #

TOOL_DEFS: list[tuple[str, str, dict]] = [
    # ---- spec lifecycle (6) ----
    ("hh_describe_process_unit",
     "Prose front door: turn a natural-language description into a draft unit_spec. It infers "
     "STRUCTURE (ports, phases, species, process names) and NEVER a magnitude - every number "
     "comes back as the REQUIRED sentinel. Refuses to guess Type A/B routing.",
     _schema({"description": S, "name": S, "category": S, "qualified_name": S, "out_path": S},
             ["description", "name"])),
    ("hh_compose_unit_spec",
     "Structured back door: build a unit_spec from explicit fields, with no NL inference. A "
     "value supplied without a provenance is REFUSED, not defaulted.",
     _schema({"fields": {"type": "object"}, "out_path": S}, ["fields"])),
    ("hh_read_unit_spec",
     "Render a stored unit_spec for human review, ordered by danger: values still owed first.",
     _schema({"spec_path": S}, ["spec_path"])),
    ("hh_edit_unit_spec",
     "Apply a structured edit at a named path (e.g. parameters[0].default.value). Setting a "
     "magnitude requires a provenance in the same call, and ANY edit clears acceptance.",
     _schema({"spec_path": S, "path": S, "value": {}, "provenance": S, "source": S},
             ["spec_path", "path"])),
    ("hh_review_unit_spec",
     "The review gate (rung 1 render): REQUIRED values, then unverified/self-asserted values, "
     "then structure and the Gujer matrix.",
     _schema({"spec_path": S}, ["spec_path"])),
    ("hh_accept_unit_spec",
     "Record explicit, timestamped human acceptance with per-value confirmation. Emission "
     "refuses without it. Bulk confirmation is recorded and costs an explicit opt-in later.",
     _schema({"spec_path": S, "accepted_by": S, "confirm_all": B}, ["spec_path", "accepted_by"])),

    # ---- the seven-rung ladder (7) ----
    ("hh_lint_unit_spec",
     "Rung 1: enforces the REQUIRED sentinel, corroborated provenance, hedge detection and "
     "routing/composite refusal. Schema validation CANNOT do this.",
     _schema({"spec_path": S}, ["spec_path"])),
    ("hh_check_dimensions",
     "Rung 1.5: dimensional consistency of units and expressions. Acceptance is ZERO FALSE "
     "POSITIVES, not a clean corpus - the shipped library contains 156 real vendor label bugs.",
     _schema({"spec_path": S, "workbook": S}, [])),
    ("hh_check_continuity",
     "Rung 2: per-process elemental continuity (COD/C/N/P/...) plus composition "
     "self-consistency. Gate is relative; the vendor 1E-15 is reported, not used as the gate.",
     _schema({"spec_path": S, "model_base": S}, [])),
    ("hh_diff_model_base",
     "Rung 2.5 (Type B only): semantic diff of a forked model base against the vendor original, "
     "keyed by symbol. Returns the additive-only gate verdict.",
     _schema({"vendor": S, "fork": S}, ["vendor", "fork"])),
    ("hh_compile_smt",
     "Rung 3: SMT24.exe. Success is the ABSENCE of [ERROR] in the invocation-CWD smtlog plus a "
     "parseable XML - never the exit code. -nosort is refused outside diagnostics.",
     _schema({"instance": S, "out_xml": S, "cwd": S, "check_symbols": ARR,
              "timeout": N, "allow_nosort": B}, ["instance", "out_xml"])),
    ("hh_compile_slcompiler",
     "Rung 4: slcompiler.exe. Success requires the link-success line AND a DLL that verifies as "
     "PE32+ x86-64 - never the exit code.",
     _schema({"xml": S, "dll_out": S, "srcdir": S, "timeout": N}, ["xml", "dll_out", "srcdir"])),
    ("hh_run_tracer_test",
     "Rung 5: conservative tracer (5a) and degenerate equivalence (5b). Asserts on ROW COUNT and "
     "callback content, never the returned job id. Refuses -nosort builds.",
     _schema({"model_dll": S, "xml": S, "nonreactive_dll": S, "nonreactive_xml": S,
              "horizon_days": N, "timeout": N}, ["model_dll", "xml"])),

    # ---- emission (5) ----
    ("hh_emit_unit_workbook",
     "Emit the unit workbook and folder from an ACCEPTED spec, using xlsxwriter. Cells are "
     "vendor-TYPED (native numbers/bools; port Size=24) - a text-typed workbook compiles "
     "clean but the GUI silently drops it (UnitPalette.LoadUnit FormatException, measured "
     "2026-09-07). Optionally also emits '<group> Group Info.xlsx' beside the workbook "
     "(group_name / default_unit / sorting_priority) so one call produces a palette-ready "
     "pair. Refuses on an unaccepted spec or a failing rung 1.",
     _schema({"spec_path": S, "out_dir": S, "allow_bulk": B, "group_name": S,
              "default_unit": S, "sorting_priority": N},
             ["spec_path", "out_dir"])),
    ("hh_emit_icon",
     "Emit the unit's .emf icon: a GDI+ placeholder, or a template copy behind an opt-in. "
     "Stamps icon=placeholder or icon=template-copy=<src>.",
     _schema({"out_path": S, "label": S, "template": S, "opt_in": B}, ["out_path"])),
    ("hh_emit_test_plant",
     "Emit the plant class + instance that make a unit compilable (SMT takes a plant instance "
     "as its entry point, never a unit). Enforces invariant I7: a REACTIVE plant is refused "
     "unless the unit itself declares the gas-transfer and flocculation symbols.",
     _schema({"unit_component": S, "build_root": S, "unit_label": S, "model": S, "reactive": B,
              "class_name": S, "instance_name": S, "instance_symbol": S, "unit_class_path": S,
              "allow_unverified_reactive": B}, ["unit_component", "build_root"])),
    ("hh_fork_model_base",
     "Type B: fork a whole model base additively. A fork with no edits is a byte-identical "
     "copy; row insertion goes through Excel COM (openpyxl drops 32 OOXML parts). Runs the "
     "rung-2.5 additive-only gate on its own output.",
     _schema({"vendor": S, "out_path": S, "additions": {"type": "object"},
              "block_index": {"type": "object"}, "verify": B, "overwrite": B},
             ["vendor", "out_path"])),
    ("hh_add_unit_to_calibrated_plant",
     "Ticket 18: admit a Type B unit to a calibrated plant. Takes the additive-only gate result "
     "as an INPUT and refuses without it; disables the unit on failure (Q14 tooth 4).",
     _schema({"spec_path": S, "gate_result": {"type": "object"}, "continuity_ok": B},
             ["spec_path", "gate_result"])),

    # ---- install and support (3) ----
    ("hh_install_process_unit",
     "The ONLY tool that writes into D:\\SUMO24, and only into the empty user overlay at "
     "Dir\\My Process Code - never the vendor tree. Opt-in required; every install writes "
     "a manifest and uninstall removes exactly what that manifest lists. "
     "action: install | uninstall | list | preflight; also installs a verified model-base fork.",
     _schema({"slug": S, "action": S, "opt_in": B, "unit_name": S, "category": S,
              "allow_uncompiled": B, "allow_bulk": B, "replace": B, "dry_run": B,
              "fork_path": S}, [])),
    ("hh_check_environment",
     "Pre-flight: SMT/slcompiler present, licence registry entry and file, DTT importable, "
     "and which rung modules loaded.",
     _schema({}, [])),
    ("hh_run_ladder",
     "Run rungs 1 -> 1.5 -> 2 in order against a spec, stopping at the first failure and "
     "returning the whole trace. Compile rungs need artefacts and are called individually.",
     _schema({"spec_path": S, "model_base": S}, ["spec_path"])),

    # ---- cleanup and rollback (3) ----
    ("hh_clean_build",
     "Wipe a slug's derived build/ and artifacts/ directories. Always safe - both regenerate.",
     _schema({"slug": S}, ["slug"])),
    ("hh_snapshot_build",
     "Tar-snapshot a slug's state under a label before a risky step.",
     _schema({"slug": S, "label": S}, ["slug", "label"])),
    ("hh_revert_build",
     "Restore a slug to a labelled snapshot.",
     _schema({"slug": S, "label": S}, ["slug", "label"])),
]

TOOL_NAMES = [t[0] for t in TOOL_DEFS]


# --------------------------------------------------------------------------- #
# Dispatch
# --------------------------------------------------------------------------- #

def dispatch(name: str, arguments: dict) -> dict:
    """Route an hh_* call. Always returns a dict; never raises across the MCP boundary."""
    a = arguments or {}
    try:
        return _dispatch(name, a)
    except Exception as e:                                   # pragma: no cover
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "tool": name}


def _dispatch(name: str, a: dict) -> dict:
    # ---- spec lifecycle ----
    if name in ("hh_describe_process_unit", "hh_compose_unit_spec"):
        if spec_builder is None:
            return _unavailable("spec_builder")
        if name == "hh_describe_process_unit":
            r = spec_builder.describe_to_spec(a.get("description", ""), a.get("name", ""),
                                              category=a.get("category", "Custom"),
                                              qualified_name=a.get("qualified_name"))
        else:
            r = spec_builder.compose_spec(a.get("fields") or {})
        if r.get("ok") and a.get("out_path"):
            r["written_to"] = _save_spec(a["out_path"], r["spec"])
        return r
    if name == "hh_edit_unit_spec":
        if spec_builder is None:
            return _unavailable("spec_builder")
        path = a.get("spec_path", "")
        spec, err = _load_spec(path)
        if err:
            return err
        r = spec_builder.edit_spec(spec, a.get("path", ""), a.get("value"),
                                   provenance=a.get("provenance"), source=a.get("source"))
        if r.get("ok"):
            # Written back only on success: a refused edit must not touch the file, or the
            # refusal would be advisory rather than actual.
            r["written_to"] = _save_spec(path, spec)
        return r
    if name in ("hh_read_unit_spec", "hh_review_unit_spec"):
        if spec_review is None:
            return _unavailable("spec_review")
        spec, err = _load_spec(a.get("spec_path", ""))
        if err:
            return err
        return {"ok": True, "rendered": spec_review.render(spec)}
    if name == "hh_accept_unit_spec":
        if spec_review is None:
            return _unavailable("spec_review")
        p = a.get("spec_path", "")
        spec, err = _load_spec(p)
        if err:
            return err
        r = spec_review.accept(spec, a.get("accepted_by", "unknown"),
                               confirm_all=bool(a.get("confirm_all")))
        if r.get("accepted"):
            pathlib.Path(p).write_text(json.dumps(spec, indent=2, ensure_ascii=False),
                                       encoding="utf-8")
        return {"ok": bool(r.get("accepted")), **r}

    # ---- ladder ----
    if name == "hh_lint_unit_spec":
        if spec_review is None:
            return _unavailable("spec_review")
        spec, err = _load_spec(a.get("spec_path", ""))
        if err:
            return err
        v = spec_review.lint(spec)
        return {"ok": v["ok"], **v}
    if name == "hh_check_dimensions":
        if dimension_checker is None:
            return _unavailable("dimension_checker")
        if a.get("workbook"):
            return {"ok": True, "report": dimension_checker.check_workbook(a["workbook"])}
        spec, err = _load_spec(a.get("spec_path", ""))
        if err:
            return err
        r = dimension_checker.check_spec(spec)
        return {"ok": bool(r.get("ok")), "report": r}
    if name == "hh_check_continuity":
        if continuity_checker is None:
            return _unavailable("continuity_checker")
        if a.get("spec_path"):
            spec, err = _load_spec(a["spec_path"])
            if err:
                return err
            r = continuity_checker.check_spec(spec, a.get("model_base", ""))
        else:
            r = continuity_checker.check_model_base_continuity(a.get("model_base", ""))
        return {"ok": bool(r.get("ok")), "report": r}
    if name == "hh_diff_model_base":
        if model_base_diff is None:
            return _unavailable("model_base_diff")
        d = model_base_diff.diff_model_bases(a["vendor"], a["fork"])
        g = model_base_diff.additive_only_gate(d)
        return {"ok": g["ok"], "gate": g, "diff_summary":
                {k: d[k] for k in ("n_added", "n_modified", "n_removed", "sheets_compared")}}
    if name == "hh_compile_smt":
        if smt_runner is None:
            return _unavailable("smt_runner")
        r = smt_runner.run_smt(a["instance"], a["out_xml"], cwd=a.get("cwd"),
                               timeout=int(a.get("timeout") or 600),
                               allow_nosort=bool(a.get("allow_nosort")),
                               check_symbols=a.get("check_symbols"))
        return {"ok": r["ok"], **r}
    if name == "hh_compile_slcompiler":
        if slc_runner is None:
            return _unavailable("slc_runner")
        r = slc_runner.run_slcompiler(a["xml"], a["dll_out"], a["srcdir"],
                                      timeout=int(a.get("timeout") or 1800))
        return {"ok": r["ok"], **r}
    if name == "hh_run_tracer_test":
        if tracer_test is None:
            return _unavailable("tracer_test")
        if a.get("nonreactive_dll") and a.get("nonreactive_xml"):
            r = tracer_test.rung5b_degenerate_equivalence(
                a["model_dll"], a["xml"], a["nonreactive_dll"], a["nonreactive_xml"],
                horizon_days=float(a.get("horizon_days") or 20.0),
                timeout_s=int(a.get("timeout") or 600))
        else:
            r = tracer_test.rung5a_conservative_tracer(
                a["model_dll"], a["xml"],
                horizon_days=float(a.get("horizon_days") or 20.0),
                timeout_s=int(a.get("timeout") or 600))
        return {"ok": bool(r.get("ok")), **r}

    # ---- emission ----
    if name == "hh_emit_unit_workbook":
        if unit_emitter is None:
            return _unavailable("unit_emitter")
        spec, err = _load_spec(a.get("spec_path", ""))
        if err:
            return err
        group_info = None
        if a.get("group_name"):
            group_info = {"name": a["group_name"],
                          "default_unit": a.get("default_unit") or "",
                          "sorting_priority": a.get("sorting_priority") or 940}
        r = unit_emitter.emit_unit(spec, a["out_dir"], allow_bulk=bool(a.get("allow_bulk")),
                                   group_info=group_info)
        return {"ok": bool(r.get("emitted")), **r}
    if name == "hh_emit_icon":
        if icon_emitter is None:
            return _unavailable("icon_emitter")
        if a.get("template"):
            r = icon_emitter.emit_from_template(a["out_path"], a["template"],
                                                opt_in=bool(a.get("opt_in")))
        else:
            r = icon_emitter.emit_placeholder(a["out_path"], label=a.get("label", ""))
        return {"ok": bool(r.get("emitted")), **r}
    if name == "hh_emit_test_plant":
        if plant_emitter is None:
            return _unavailable("plant_emitter")
        r = plant_emitter.emit_test_plant(
            a.get("unit_component", ""), a.get("build_root", ""),
            unit_label=a.get("unit_label", "CSTR"), model=a.get("model", "Sumo2C"),
            reactive=bool(a.get("reactive")), class_name=a.get("class_name", "Plant"),
            instance_name=a.get("instance_name"), instance_symbol=a.get("instance_symbol"),
            unit_class_path=a.get("unit_class_path"),
            allow_unverified_reactive=bool(a.get("allow_unverified_reactive")))
        return {"ok": bool(r.get("emitted")), **r}
    if name == "hh_fork_model_base":
        if model_base_fork is None:
            return _unavailable("model_base_fork")
        r = model_base_fork.fork_model_base(
            a["vendor"], a["out_path"], additions=a.get("additions"),
            block_index=a.get("block_index"),
            verify=a.get("verify", True), overwrite=bool(a.get("overwrite")))
        return {"ok": bool(r.get("forked")), **r}
    if name == "hh_add_unit_to_calibrated_plant":
        if model_base_diff is None:
            return _unavailable("model_base_diff")
        spec, err = _load_spec(a.get("spec_path", ""))
        if err:
            return err
        r = model_base_diff.type_b_admission(spec, a.get("gate_result"),
                                             continuity_ok=bool(a.get("continuity_ok")))
        return {"ok": bool(r.get("admitted")), **r}

    # ---- install and support ----
    if name == "hh_install_process_unit":
        return _install(a)
    if name == "hh_check_environment":
        return _check_environment()
    if name == "hh_run_ladder":
        return _run_ladder(a)

    # ---- cleanup and rollback ----
    if name in ("hh_clean_build", "hh_snapshot_build", "hh_revert_build"):
        if sumoslang_author is None:
            return _unavailable("sumoslang_author")
        try:
            if name == "hh_clean_build":
                return {"ok": True, "result": sumoslang_author.clean_build(a["slug"])}
            if name == "hh_snapshot_build":
                return {"ok": True, "snapshot": sumoslang_author.snapshot_build(a["slug"], a["label"])}
            return {"ok": True, "restored_from": sumoslang_author.revert_build(a["slug"], a["label"])}
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    return {"ok": False, "error": f"unknown Group HH tool: {name}"}


def _save_spec(path: str, spec: dict) -> str:
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(spec, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(p)


def _install(a: dict) -> dict:
    """Route the install tool four ways.

    Uninstall and listing live behind an `action` rather than as separate tools: the inventory
    is 24 by a user decision, and adding tools to expose the inverse of one is how a surface
    grows without anyone choosing to grow it.
    """
    if unit_installer is None:
        return _unavailable("unit_installer")
    action = (a.get("action") or "install").lower()

    if action == "list":
        return unit_installer.list_installed(a.get("category"))
    if action == "preflight":
        slug = unit_installer._find_slug(a.get("slug", ""))
        if slug is None:
            return {"ok": False, "error": "slug directory not found: %s" % a.get("slug")}
        r = unit_installer.preflight(slug, a.get("unit_name"),
                                     allow_uncompiled=bool(a.get("allow_uncompiled")),
                                     allow_bulk=bool(a.get("allow_bulk")))
        return {"ok": bool(r.get("ok")), **r}
    if action == "uninstall":
        r = unit_installer.uninstall_process_unit(a.get("slug", ""),
                                                  opt_in=bool(a.get("opt_in")))
        return {"ok": bool(r.get("uninstalled")), **r}
    if action != "install":
        return {"ok": False, "error": "unknown action %r" % action,
                "detail": ["install | uninstall | list | preflight"]}

    if a.get("fork_path"):
        r = unit_installer.install_model_base(
            a["fork_path"], opt_in=bool(a.get("opt_in")),
            category=a.get("category") or unit_installer.DEFAULT_MODEL_CATEGORY,
            replace=bool(a.get("replace")), dry_run=bool(a.get("dry_run")))
        return {"ok": bool(r.get("installed")), **r}

    r = unit_installer.install_process_unit(
        a.get("slug", ""), opt_in=bool(a.get("opt_in")), unit_name=a.get("unit_name"),
        category=a.get("category") or unit_installer.DEFAULT_CATEGORY,
        allow_uncompiled=bool(a.get("allow_uncompiled")),
        allow_bulk=bool(a.get("allow_bulk")),
        replace=bool(a.get("replace")), dry_run=bool(a.get("dry_run")))
    return {"ok": bool(r.get("installed")), **r}


def _check_environment() -> dict:
    from sumo_paths import installation_path, resolve_install_dir
    smt = installation_path("SMT24.exe")
    slc = installation_path("slcompiler.exe")
    lic_path, lic_ok = None, False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"SOFTWARE\Dynamita\Sumo24\PATHS") as k:
            lic_path, _ = winreg.QueryValueEx(k, "License")
            lic_ok = bool(lic_path) and pathlib.Path(lic_path).exists()
    except Exception as e:
        lic_path = f"(registry unreadable: {e})"
    try:
        import dynamita.scheduler  # noqa: F401
        dtt = True
    except Exception:
        dtt = False
    modules = {m: (globals().get(m) is not None) for m in
               ("spec_review", "dimension_checker", "continuity_checker", "model_base_diff",
                "smt_runner", "slc_runner", "tracer_test", "unit_emitter", "icon_emitter",
                "sumoslang_author", "spec_builder", "plant_emitter", "model_base_fork",
                "unit_installer")}
    return {"ok": smt.exists() and slc.exists() and all(modules.values()),
            "smt_present": smt.exists(), "slcompiler_present": slc.exists(),
            "licence_registry": str(lic_path), "licence_file_present": lic_ok,
            "dtt_importable": dtt,
            "native_runtime_verified": False,
            "install_dir": str(resolve_install_dir() or ""),
            "rung_modules": modules,
            "import_errors": _IMPORT_ERRORS,
            "note": "Importable does not establish runtime readiness. Compile rungs need no licence; the runtime (rung 5) does."}


def _run_ladder(a: dict) -> dict:
    """Rungs 1 -> 1.5 -> 2, stopping at the first failure. Compile rungs are called separately."""
    trace = []
    for tool, args in (("hh_lint_unit_spec", {"spec_path": a.get("spec_path")}),
                       ("hh_check_dimensions", {"spec_path": a.get("spec_path")}),
                       ("hh_check_continuity", {"spec_path": a.get("spec_path"),
                                                "model_base": a.get("model_base", "")})):
        r = dispatch(tool, args)
        trace.append({"rung": tool, "ok": r.get("ok"),
                      "summary": r.get("errors") or r.get("reason") or "ok"})
        if not r.get("ok"):
            return {"ok": False, "stopped_at": tool, "trace": trace,
                    "detail": "rung 1 must pass before any SMT call - an invalid unit HANGS "
                              "the SMT rather than erroring."}
    return {"ok": True, "trace": trace}


if __name__ == "__main__":                                   # pragma: no cover
    print(f"{len(TOOL_DEFS)} Group HH tools")
    for n, d, _ in TOOL_DEFS:
        print(f"  {n:34s} {d[:60]}")
