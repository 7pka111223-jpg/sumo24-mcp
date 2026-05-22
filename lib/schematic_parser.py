"""
schematic_parser.py
───────────────────
Parsing, validation, and command-generation for WWTP schematics produced by
the HTML builder `wwtp_schematic_template.html`.

The MCP server tools in Group BB (schematic ↔ SUMO) call into this module.
Kept dependency-free (stdlib only) so it imports even if openpyxl/numpy/etc.
are not installed.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

try:
    from unit_type_registry import (
        UNIT_TYPES,
        STREAM_TYPES,
        STREAM_TO_DTT,
        BOUNDARY_TYPES,
        is_known_unit_type,
    )
except ImportError:  # pragma: no cover — runs when the file is executed elsewhere
    from .unit_type_registry import (  # type: ignore
        UNIT_TYPES,
        STREAM_TYPES,
        STREAM_TO_DTT,
        BOUNDARY_TYPES,
        is_known_unit_type,
    )


# ── HTML / JSON extraction ────────────────────────────────────────────────────

_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_SCHEMATIC_BLOCK = re.compile(
    r'<script[^>]*id\s*=\s*["\']schematic-data["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)


def extract_json_from_html(filepath: str | os.PathLike) -> dict[str, Any]:
    """Read a saved schematic HTML and return its embedded JSON dict.

    Strips HTML comments first so a doc-comment that references the same script
    tag literally doesn't confuse the regex.
    """
    text = Path(filepath).read_text(encoding="utf-8")
    text_clean = _HTML_COMMENT.sub("", text)
    m = _SCHEMATIC_BLOCK.search(text_clean)
    if not m:
        raise ValueError(
            "No <script id='schematic-data'> block found in HTML. "
            "Make sure the file was produced via 'Save HTML (for MCP)' in the builder."
        )
    block = m.group(1).strip()
    if not block:
        raise ValueError("Schematic <script> block is empty.")
    try:
        data = json.loads(block)
    except json.JSONDecodeError as e:
        raise ValueError(f"Embedded schematic JSON is malformed: {e}") from e
    return data


def load_schematic(filepath: str | os.PathLike) -> dict[str, Any]:
    """Load a schematic from either .html or .json by extension."""
    p = Path(filepath)
    if not p.exists():
        raise FileNotFoundError(f"Schematic file not found: {p}")
    suffix = p.suffix.lower()
    if suffix in (".html", ".htm"):
        return extract_json_from_html(p)
    if suffix == ".json":
        return json.loads(p.read_text(encoding="utf-8"))
    # Try HTML extraction first, fall back to JSON
    try:
        return extract_json_from_html(p)
    except Exception:
        return json.loads(p.read_text(encoding="utf-8"))


# ── Validation ───────────────────────────────────────────────────────────────

def validate_schematic(data: dict[str, Any]) -> dict[str, list[str]]:
    """Return {'errors': [...], 'warnings': [...]} per the contract in COWORK_PROJECT.md."""
    errors: list[str] = []
    warnings: list[str] = []

    # schema_version
    if data.get("schema_version") != "1.0":
        errors.append(f"schema_version must be '1.0' (got {data.get('schema_version')!r})")

    units = data.get("units") or []
    streams = data.get("streams") or []

    if not isinstance(units, list):
        errors.append("'units' must be a list")
        return {"errors": errors, "warnings": warnings}
    if not isinstance(streams, list):
        errors.append("'streams' must be a list")
        return {"errors": errors, "warnings": warnings}

    if not units:
        errors.append(
            "Schematic contains no units. Did you click 'Save HTML (for MCP)' after editing? "
            "The raw template downloads with an empty units array."
        )

    # id uniqueness
    ids = [u.get("id") for u in units]
    dups = {i for i in ids if ids.count(i) > 1}
    if dups:
        errors.append(f"Duplicate unit ids: {sorted(dups)}")

    # unknown types
    unknown = sorted({u.get("type") for u in units if u.get("type") and not is_known_unit_type(u["type"])})
    if unknown:
        errors.append(f"Unknown unit types: {unknown}")

    # boundary cardinality
    inf_count = sum(1 for u in units if u.get("type") == "influent")
    eff_count = sum(1 for u in units if u.get("type") == "effluent")
    if inf_count == 0:
        errors.append("No 'influent' unit defined.")
    elif inf_count > 1:
        warnings.append(f"Multiple influent units ({inf_count}) — only one is typical.")
    if eff_count == 0:
        warnings.append("No 'effluent' unit defined.")

    # stream references
    id_set = set(ids)
    for s in streams:
        if s.get("from") not in id_set:
            errors.append(f"Stream {s.get('id')}: 'from' unit {s.get('from')!r} not defined")
        if s.get("to") not in id_set:
            errors.append(f"Stream {s.get('id')}: 'to' unit {s.get('to')!r} not defined")
        if s.get("type") not in STREAM_TYPES:
            errors.append(f"Stream {s.get('id')}: unknown type {s.get('type')!r}")

    # topology (non-boundary units should have ≥1 in and ≥1 out)
    for u in units:
        if u.get("type") in BOUNDARY_TYPES:
            continue
        has_in  = any(s.get("to")   == u.get("id") for s in streams)
        has_out = any(s.get("from") == u.get("id") for s in streams)
        if not has_in:
            warnings.append(f"Unit {u.get('id')} ({u.get('name')}) has no incoming stream")
        if not has_out:
            warnings.append(f"Unit {u.get('id')} ({u.get('name')}) has no outgoing stream")

    # parameter sanity (negative volumes etc.)
    for u in units:
        for p in u.get("parameters") or []:
            v = p.get("value")
            if isinstance(v, (int, float)) and v < 0 and p.get("key") not in (None, ""):
                warnings.append(f"{u.get('id')}.{p.get('key')} is negative ({v})")

    return {"errors": errors, "warnings": warnings}


# ── Command generation ──────────────────────────────────────────────────────

def _header_lines(data: dict[str, Any]) -> list[str]:
    meta = data.get("meta") or {}
    return [
        "# ─────────────────────────────────────────────────────────────",
        "# SumoCore parameter script generated from schematic",
        f"# Plant: {meta.get('plant_name','')}",
        f"# Design Flow: {meta.get('design_flow_m3d','')} m3/d",
        f"# Temperature: {meta.get('temperature_C','')} °C",
        f"# Generated: {meta.get('modified','')}",
        "# ─────────────────────────────────────────────────────────────",
    ]


def schematic_to_commands(data: dict[str, Any]) -> list[str]:
    """Translate a parsed schematic into SumoCore parameter override commands."""
    cmds: list[str] = list(_header_lines(data))
    meta = data.get("meta") or {}

    # global temperature applied to influent
    T = meta.get("temperature_C")
    if T is not None:
        cmds.append(f"set Sumo__Plant__Influent__param__T {T}")

    units = data.get("units") or []
    for unit in units:
        params = unit.get("parameters") or []
        if not params:
            continue
        cmds.append(f'# Unit {unit.get("id")} ({unit.get("name")}) — {unit.get("type")}')
        for p in params:
            sv = p.get("sumo_variable")
            v  = p.get("value")
            if sv is not None and v is not None:
                cmds.append(f"set {sv} {v}")
        cmds.append("")

    # topology recorded as comments — see CC tools for actual addconnection generation
    cmds.append("# Stream topology (informational — true topology is in .sumo file)")
    for s in data.get("streams") or []:
        cmds.append(
            f"# {s.get('id')}: {s.get('from')} -> {s.get('to')}"
            f"  ({s.get('type')})"
            + (f' "{s.get("label")}"' if s.get("label") else "")
        )
    return cmds


def schematic_to_dtt_actions(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Translate a schematic into DTT-style 'addprocess + addconnection + setparameter' steps.

    This is what build_model_from_schematic uses when apply_via_dtt=True.
    Returns a list of dicts that the server's DTT bridge can execute one by one.
    """
    actions: list[dict[str, Any]] = []
    meta = data.get("meta") or {}
    units = data.get("units") or []
    streams = data.get("streams") or []

    # 1. add processes
    for u in units:
        actions.append({
            "step": "addprocess",
            "args": {
                "name": u.get("id"),
                "class": (UNIT_TYPES.get(u.get("type")) or {}).get("sumo_unit_class", "CSTR"),
                "x": (u.get("position") or {}).get("x", 0),
                "y": (u.get("position") or {}).get("y", 0),
                "label": u.get("name"),
            },
        })

    # 2. connect streams
    for s in streams:
        actions.append({
            "step": "connect",
            "args": {
                "from": s.get("from"),
                "to":   s.get("to"),
                "connection_type": STREAM_TO_DTT.get(s.get("type"), "process"),
                "label": s.get("label", ""),
            },
        })

    # 3. set parameters
    if meta.get("temperature_C") is not None:
        actions.append({
            "step": "setparameter",
            "args": {"name": "Sumo__Plant__Influent__param__T", "value": meta["temperature_C"]},
        })

    for u in units:
        for p in u.get("parameters") or []:
            if p.get("sumo_variable") and p.get("value") is not None:
                actions.append({
                    "step": "setparameter",
                    "args": {"name": p["sumo_variable"], "value": p["value"]},
                })

    return actions


# ── Comparison against an existing compiled model ─────────────────────────

def compare_to_model(data: dict[str, Any], model_unit_ids: list[str] | None = None) -> dict[str, Any]:
    """Diff schematic against a list of unit IDs already in the compiled model.

    Returns: { matched, missing_in_model, extra_in_model, parameter_overrides_count }.
    If `model_unit_ids` is None we still report what the schematic intends to override.
    """
    units = data.get("units") or []
    schematic_ids = {u.get("id") for u in units}
    overrides = sum(len(u.get("parameters") or []) for u in units)
    if model_unit_ids is None:
        return {
            "matched": [],
            "missing_in_model": [],
            "extra_in_model": [],
            "parameter_overrides_count": overrides,
            "note": "No compiled-model unit list provided; only override count was computed.",
        }
    model_set = set(model_unit_ids)
    return {
        "matched":          sorted(schematic_ids & model_set),
        "missing_in_model": sorted(schematic_ids - model_set),
        "extra_in_model":   sorted(model_set - schematic_ids),
        "parameter_overrides_count": overrides,
    }


# ── SumoSlang skeleton (advanced / stretch) ───────────────────────────────

def schematic_to_sumoslang(data: dict[str, Any]) -> str:
    """Render a *skeleton* SumoSlang plant definition.

    This is NOT a complete SumoSlang program — it gives the topology and
    parameter scaffolding. Users still need to hand-edit kinetic constants
    before SUMO will accept it. Treat output as a starting point.
    """
    meta = data.get("meta") or {}
    units = data.get("units") or []
    streams = data.get("streams") or []
    L: list[str] = []
    L.append(f"// SumoSlang skeleton generated from schematic")
    L.append(f"// Plant: {meta.get('plant_name','')}")
    L.append(f"// Design Q: {meta.get('design_flow_m3d','')} m3/d")
    L.append(f"// Temperature: {meta.get('temperature_C','')} °C")
    L.append("")
    L.append('plant "Plant" {')
    L.append("    // ── Unit declarations ─────────────────────────────────")
    for u in units:
        cls = (UNIT_TYPES.get(u.get("type")) or {}).get("sumo_unit_class", "CSTR")
        L.append(f'    {u["id"]} : {cls};   // {u.get("name")} [{u.get("type")}]')
    L.append("")
    L.append("    // ── Connections ──────────────────────────────────────")
    for s in streams:
        L.append(f'    connect {s["from"]}.out -> {s["to"]}.in;   // {s["type"]}')
    L.append("")
    L.append("    // ── Parameters ───────────────────────────────────────")
    for u in units:
        for p in u.get("parameters") or []:
            sv = p.get("sumo_variable")
            if sv:
                L.append(f"    {sv} = {p['value']};   // {p.get('description','')} [{p.get('unit','')}]")
    L.append("}")
    return "\n".join(L)


# ── Helpers ──────────────────────────────────────────────────────────────

def summarise(data: dict[str, Any]) -> dict[str, Any]:
    """Compact summary suitable for logging."""
    units = data.get("units") or []
    streams = data.get("streams") or []
    meta = data.get("meta") or {}
    by_cat: dict[str, int] = {}
    for u in units:
        cat = (UNIT_TYPES.get(u.get("type")) or {}).get("category", "unknown")
        by_cat[cat] = by_cat.get(cat, 0) + 1
    by_stream: dict[str, int] = {}
    for s in streams:
        by_stream[s.get("type", "?")] = by_stream.get(s.get("type", "?"), 0) + 1
    return {
        "plant_name":      meta.get("plant_name"),
        "design_flow_m3d": meta.get("design_flow_m3d"),
        "temperature_C":   meta.get("temperature_C"),
        "unit_count":      len(units),
        "stream_count":    len(streams),
        "units_by_category": by_cat,
        "streams_by_type":   by_stream,
    }
