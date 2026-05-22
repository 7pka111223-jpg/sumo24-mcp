"""
pipeline/manifest.py
────────────────────
project.yaml read/write, schema enforcement, hash-chain management.

The manifest is the single source of truth for pipeline state.
It lives at <project_dir>/project.yaml and is read/written by every
stage tool.  All mutations go through the helpers here so schema
invariants are always maintained.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
from datetime import datetime
from typing import Any

try:
    from ruamel.yaml import YAML as _YAML_CLS
    _yaml_inst = _YAML_CLS()
    _yaml_inst.preserve_quotes = True
    _yaml_inst.indent(mapping=2, sequence=4, offset=2)
    HAS_RUAMEL = True

    def _load_yaml(text: str) -> dict:
        return dict(_yaml_inst.load(text))

    def _dump_yaml(obj: dict) -> str:
        import io
        buf = io.StringIO()
        _yaml_inst.dump(obj, buf)
        return buf.getvalue()

except ImportError:
    import yaml as _yaml_plain  # type: ignore
    HAS_RUAMEL = False

    def _load_yaml(text: str) -> dict:          # type: ignore[misc]
        return _yaml_plain.safe_load(text)

    def _dump_yaml(obj: dict) -> str:            # type: ignore[misc]
        return _yaml_plain.safe_dump(obj, sort_keys=False, allow_unicode=True)


# ── Stage catalogue ──────────────────────────────────────────────────────────
STAGES = [
    "init",               # 0
    "configuration",      # 1  – HTML schematic
    "parameters",         # 2  – Excel template
    "engineering_checks", # 3  – SRT/HRT/F:M/mass-balance
    "static_inputs",      # 4  – ASM state-variable initial values
    "dynamic_inputs",     # 5  – dynamic input TSVs (optional)
    "controllers",        # 6  – controller definitions (optional)
    "build",              # 7  – sumo-pack assembly
    "verification",       # 8  – post-SUMO-compile verification
]

OPTIONAL_STAGES = {5, 6}   # may be skipped with an explicit reason

# Artefact paths relative to project_dir, keyed by stage id
_STAGE_ARTEFACTS: dict[int, str] = {
    0: "project.yaml",
    1: "{plant_name}_schematic.html",
    2: "{plant_name}_data.xlsx",
    3: "engineering_checks.json",
    4: "static_inputs.json",
    6: "controllers.json",
    7: "{plant_name}.sumo-pack",
}


# ── File-system helpers ──────────────────────────────────────────────────────

def manifest_path(project_dir: "str | pathlib.Path") -> pathlib.Path:
    return pathlib.Path(project_dir) / "project.yaml"


def load(project_dir: "str | pathlib.Path") -> dict:
    p = manifest_path(project_dir)
    if not p.exists():
        raise FileNotFoundError(
            f"No project.yaml in {project_dir} — call pipeline_init first"
        )
    return _load_yaml(p.read_text(encoding="utf-8"))


def save(project_dir: "str | pathlib.Path", manifest: dict) -> None:
    manifest["modified"] = datetime.utcnow().isoformat() + "Z"
    p = manifest_path(project_dir)
    # Atomic write: write to temp then rename
    tmp = p.with_suffix(".yaml.tmp")
    tmp.write_text(_dump_yaml(manifest), encoding="utf-8")
    tmp.replace(p)


# ── Factory ───────────────────────────────────────────────────────────────────

def new_manifest(project_dir: str, plant_name: str,
                 kinetic_model: str = "ASM2d") -> dict:
    now = datetime.utcnow().isoformat() + "Z"
    return {
        "schema_version": 1,
        "plant_name": plant_name,
        "project_dir": str(project_dir),
        "kinetic_model": kinetic_model,
        "created": now,
        "modified": now,
        "stages": [
            {
                "id": i,
                "name": STAGES[i],
                "status": "pending",
                "completed_at": None,
                "artefact_path": _STAGE_ARTEFACTS.get(i, ""),
                "input_hash": None,
                "output_hash": None,
                "based_on": None,
                "summary": None,
                "blocker": None,
            }
            for i in range(len(STAGES))
        ],
        "provenance": [],
        "plant_summary": {
            "plant_name": plant_name,
            "kinetic_model": kinetic_model,
        },
    }


# ── Stage accessors ──────────────────────────────────────────────────────────

def get_stage(manifest: dict, stage_id: int) -> dict:
    return manifest["stages"][stage_id]


def set_stage(manifest: dict, stage_id: int, **fields) -> None:
    s = manifest["stages"][stage_id]
    s.update(fields)
    if fields.get("status") in ("passed", "failed", "skipped"):
        s["completed_at"] = datetime.utcnow().isoformat() + "Z"


def last_passed_hash(manifest: dict, before_stage: int) -> "str | None":
    """Return the output_hash of the latest passed/skipped stage before stage N."""
    for i in range(before_stage - 1, -1, -1):
        s = manifest["stages"][i]
        if s["status"] in ("passed", "skipped"):
            return s.get("output_hash")
    return None


def mark_downstream_stale(manifest: dict, from_stage: int) -> list[int]:
    """Mark every passed stage after from_stage as stale.  Returns affected ids."""
    stale: list[int] = []
    for i in range(from_stage + 1, len(STAGES)):
        s = manifest["stages"][i]
        if s["status"] == "passed":
            s["status"] = "stale"
            stale.append(i)
    return stale


def record(manifest: dict, tool: str, args: dict, result: str) -> None:
    """Append a provenance entry (append-only)."""
    manifest.setdefault("provenance", []).append(
        {
            "ts": datetime.utcnow().isoformat() + "Z",
            "tool": tool,
            "args": {k: str(v)[:200] for k, v in args.items()},  # truncate long values
            "result": result,
        }
    )


def artefact_path(manifest: dict, stage_id: int) -> "pathlib.Path | None":
    """Return the resolved artefact path for a stage, or None if not applicable."""
    template = _STAGE_ARTEFACTS.get(stage_id)
    if not template:
        return None
    name = manifest.get("plant_name", "plant")
    rel = template.format(plant_name=name)
    return pathlib.Path(manifest["project_dir"]) / rel
