"""
pipeline/build.py
──────────────────
Stage 7: assemble the full build pack from all prior stage artefacts.

This wraps sumo_pack.build_sumo_pack() and adds:
  - static_inputs.scs from Stage 4
  - controllers.scs from Stage 6 (if not skipped)
  - dynamic_inputs/*.tsv from Stage 5 (if not skipped)
  - project.yaml snapshot
  - engineering_checks.json
  - A generated BUILD_INSTRUCTIONS.md tailored to what stages are present

The pack directory: <project_dir>/<plant_name>.sumo-pack/
"""
from __future__ import annotations

import json
import pathlib
import shutil
from datetime import datetime
from typing import Any


_STUB_XML = """\
<?xml version="1.0" encoding="utf-8"?>
<SumoProject name="{plant_name}" version="24">
  <!-- Open this file in SUMO24 GUI to build the process network -->
  <!-- 1. Paste plant.sumoslang in the SumoSlang editor and click Compile -->
  <!-- 2. In Core Window: maptoic; save "state.xml"; -->
  <!-- 3. Paste apply_parameters.scs; save "state.xml"; -->
  <!-- 4. Paste static_inputs.scs;   save "state.xml"; -->
  <!-- 5. (Optional) Import dynamic_inputs/*.tsv via Inputs -> Import -->
  <!-- 6. (Optional) Paste controllers.scs; save "state.xml"; -->
</SumoProject>
"""


def _make_build_instructions(
    plant_name: str,
    pack_dir: pathlib.Path,
    has_static: bool,
    has_dynamic: bool,
    has_controllers: bool,
) -> str:
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"# Build {plant_name} in SUMO24",
        f"",
        f"Generated {now} by SUMO24 MCP pipeline.",
        f"",
        f"## 1. Open the stub",
        f"File → Open → {plant_name}.sumo  ({pack_dir / f'{plant_name}.sumo'})",
        f"",
        f"## 2. Compile the topology",
        f"Edit → Plant Definition (or SumoSlang panel)",
        f"Paste the contents of: `plant.sumoslang`",
        f"Click **Compile**. SUMO writes `sumoproject.dll` next to {plant_name}.sumo.",
        f"",
        f"## 3. Save initial state",
        f"Simulate → Initialize",
        f"Wait for 'Ready for simulation'",
        f"Advanced → Core Window:",
        f"```",
        f'maptoic; save "state.xml";',
        f"```",
        f"",
        f"## 4. Apply unit parameters",
        f"Core Window — paste the contents of `apply_parameters.scs`:",
        f"```",
        f'save "state.xml";',
        f"```",
        f"",
    ]
    step = 5
    if has_static:
        lines += [
            f"## {step}. Apply static input values",
            f"Core Window — paste the contents of `static_inputs.scs`:",
            f"```",
            f'save "state.xml";',
            f"```",
            f"",
        ]
        step += 1

    if has_dynamic:
        lines += [
            f"## {step}. Load dynamic inputs",
            f"Inputs → Import:",
            f"  - dynamic_inputs/*.tsv  (select your chosen profile)",
            f"",
        ]
        step += 1

    if has_controllers:
        lines += [
            f"## {step}. Configure controllers",
            f"Core Window — paste the contents of `controllers.scs`:",
            f"```",
            f'save "state.xml";',
            f"```",
            f"",
        ]
        step += 1

    lines += [
        f"## {step}. Verify",
        f"Run Simulate → Steady State.",
        f"If it converges, return to MCP and call:",
        f"```",
        f"stage8_verify(project_dir=...)",
        f"```",
        f"",
    ]
    return "\n".join(lines)


def build_pack(
    project_dir: "str | pathlib.Path",
    plant_name: str,
    schematic: dict,
    parameters_scs: str,
    stage5_skipped: bool = True,
    stage6_skipped: bool = True,
) -> dict:
    """
    Assemble the build pack directory.

    Parameters
    ----------
    project_dir       : root project directory
    plant_name        : used for naming files
    schematic         : parsed schematic dict (from schematic_parser)
    parameters_scs    : the apply_parameters.scs text (from sumo_pack)
    stage5_skipped    : if False, copies dynamic_inputs/ into the pack
    stage6_skipped    : if False, copies controllers.scs into the pack

    Returns {ok, pack_dir, files, warnings}
    """
    pd = pathlib.Path(project_dir)
    pack_dir = pd / f"{plant_name}.sumo-pack"

    # Wipe and recreate
    if pack_dir.exists():
        shutil.rmtree(pack_dir)
    pack_dir.mkdir(parents=True)

    warnings: list[str] = []
    files: list[str] = []

    # ── plant.sumoslang ──────────────────────────────────────────────────────
    try:
        import sumo_pack as _spk
        sl_result = _spk.schematic_to_sumoslang(schematic)
        if not sl_result.get("ok"):
            return {"ok": False,
                    "error": "sumo_pack.schematic_to_sumoslang failed: "
                             + sl_result.get("error", "unknown")}
        sumoslang_text = sl_result.get("sumoslang", "")
    except Exception as ex:
        return {"ok": False, "error": f"sumo_pack module error: {ex}"}

    (pack_dir / "plant.sumoslang").write_text(sumoslang_text, encoding="utf-8")
    files.append("plant.sumoslang")

    # ── apply_parameters.scs ────────────────────────────────────────────────
    (pack_dir / "apply_parameters.scs").write_text(parameters_scs, encoding="utf-8")
    files.append("apply_parameters.scs")

    # ── static_inputs.scs ────────────────────────────────────────────────────
    static_scs = pd / "static_inputs.scs"
    has_static = static_scs.exists()
    if has_static:
        shutil.copy2(static_scs, pack_dir / "static_inputs.scs")
        files.append("static_inputs.scs")
    else:
        warnings.append("static_inputs.scs not found — Stage 4 may not be complete")

    # ── dynamic_inputs/ ──────────────────────────────────────────────────────
    dyn_src = pd / "dynamic_inputs"
    has_dynamic = not stage5_skipped and dyn_src.exists() and any(dyn_src.glob("*.tsv"))
    if has_dynamic:
        dyn_dst = pack_dir / "dynamic_inputs"
        shutil.copytree(dyn_src, dyn_dst)
        files.append("dynamic_inputs/")
    elif not stage5_skipped:
        warnings.append("Stage 5 not skipped but no dynamic_inputs/*.tsv found")

    # ── controllers.scs ──────────────────────────────────────────────────────
    ctrl_src = pd / "controllers.scs"
    has_controllers = not stage6_skipped and ctrl_src.exists()
    if has_controllers:
        shutil.copy2(ctrl_src, pack_dir / "controllers.scs")
        files.append("controllers.scs")
    elif not stage6_skipped:
        warnings.append("Stage 6 not skipped but controllers.scs not found")

    # ── schematic.json ────────────────────────────────────────────────────────
    schematic_json = json.dumps(schematic, indent=2, ensure_ascii=False)
    (pack_dir / "schematic.json").write_text(schematic_json, encoding="utf-8")
    files.append("schematic.json")

    # ── engineering_checks.json ───────────────────────────────────────────────
    ec_src = pd / "engineering_checks.json"
    if ec_src.exists():
        shutil.copy2(ec_src, pack_dir / "engineering_checks.json")
        files.append("engineering_checks.json")

    # ── project.yaml snapshot ─────────────────────────────────────────────────
    proj_yaml = pd / "project.yaml"
    if proj_yaml.exists():
        shutil.copy2(proj_yaml, pack_dir / "project.yaml")
        files.append("project.yaml")

    # ── .sumo stub ────────────────────────────────────────────────────────────
    stub_text = _STUB_XML.format(plant_name=plant_name)
    (pack_dir / f"{plant_name}.sumo").write_text(stub_text, encoding="utf-8")
    files.append(f"{plant_name}.sumo")

    # ── BUILD_INSTRUCTIONS.md ─────────────────────────────────────────────────
    instructions = _make_build_instructions(
        plant_name, pack_dir,
        has_static, has_dynamic, has_controllers,
    )
    (pack_dir / "BUILD_INSTRUCTIONS.md").write_text(instructions, encoding="utf-8")
    files.append("BUILD_INSTRUCTIONS.md")

    return {
        "ok": True,
        "pack_dir": str(pack_dir),
        "files": files,
        "has_static_inputs": has_static,
        "has_dynamic_inputs": has_dynamic,
        "has_controllers": has_controllers,
        "warnings": warnings,
    }


def generate_controllers_scs(plant_name: str, controllers: list[dict]) -> str:
    """
    Convert controllers.json entries into a SUMO Core-Window SCS script.
    """
    lines = [
        f"// controllers.scs — generated by SUMO24 MCP pipeline",
        f"// Plant: {plant_name}",
        f"// Generated: {datetime.utcnow().isoformat()}Z",
        f"// Paste in SUMO Core Window AFTER static_inputs.scs",
        "",
    ]
    for c in controllers:
        kind   = c.get("kind", "DO")
        unit   = c.get("unit", "")
        sp     = c.get("setpoint", c.get("setpoint_days", 0))
        sensor = c.get("sensor", "")
        act    = c.get("actuator", "")
        Kp     = c.get("Kp", 10)
        Ti     = c.get("Ti", 0.01)
        lines += [
            f"// {kind} controller on {unit}",
            f'set "{unit}__ctrl__{kind}__setpoint" = {sp};',
            f'set "{unit}__ctrl__{kind}__Kp" = {Kp};',
            f'set "{unit}__ctrl__{kind}__Ti" = {Ti};',
            "",
        ]
    lines.append('save "state.xml";')
    return "\n".join(lines)
