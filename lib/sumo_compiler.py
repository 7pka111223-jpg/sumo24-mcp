"""
sumo_compiler.py
─────────────────
Pure-stdlib compiler that turns a validated schematic dict (produced by
schematic_parser.py) into an actual .sumo project file.

A SUMO project file is a zip container with these members:
    manifest.xml      ── unit list, connections, parameter overrides
    state.xml         ── steady-state initial values
    metadata.json     ── extra metadata (plant name, generator, timestamps)
    sumoslang.txt     ── (optional) the SumoSlang skeleton text

A companion sumoproject.dll must sit alongside the .sumo file so SUMO can
load it; that companion is NOT bundled inside the zip, it lives next to it
on disk. The attach_companion_dll helper copies one in.

This module deliberately uses only stdlib (zipfile, xml.etree, json, pathlib),
so it works without DTT installed. It is the "headless" build path:

    schematic dict
       │
       ▼
    build_manifest_xml ──► manifest.xml
    build_state_xml    ──► state.xml
    build_metadata_json ─► metadata.json
       │
       ▼
    zip them into one .sumo file
       │
       ▼
    (optionally) copy a sumoproject.dll alongside it

The end product is loadable by `diagnose_sumo_file` and the DTT bridge.
"""

# ---------------------------------------------------------------------------
# DEPRECATED — DO NOT USE FOR NEW CALLERS.
#
# This module writes a ZIP of manifest.xml + state.xml + metadata.json under
# a .sumo extension. SUMO24 does NOT consume that format. The zip is valid
# as a zip; it is not valid as a SUMO project. Files produced by this
# module either fail to open in SUMO or open as an empty project.
#
# Use sumo_pack.py instead, which produces a build-pack directory the user
# can apply inside SUMO to get a working project.
#
# Group DD tools (compile_schematic_to_sumo, build_sumo_from_html,
# attach_companion_dll, verify_sumo_file_against_schematic) are scheduled
# for replacement. See SUMO24_MCP_Fix_Plan.md.
# ---------------------------------------------------------------------------

from __future__ import annotations

import json
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape as xml_escape

try:
    from . import unit_type_registry as _utr  # type: ignore
    from . import schematic_parser as _schp   # type: ignore
except Exception:
    import unit_type_registry as _utr         # type: ignore
    import schematic_parser as _schp          # type: ignore


# ── XML BUILDERS ─────────────────────────────────────────────────────────


def _xe(s: Any) -> str:
    """Escape a value for XML attribute / text content."""
    return xml_escape("" if s is None else str(s), {'"': "&quot;", "'": "&apos;"})


def build_manifest_xml(schematic: dict) -> str:
    """Render the schematic as a SUMO project manifest.xml."""
    meta = schematic.get("meta", {}) or {}
    units = schematic.get("units", []) or []
    streams = schematic.get("streams", []) or []
    lines: list[str] = []
    lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    lines.append(
        f'<sumoproject schema="1.0" generator="sumo24-mcp" plant="{_xe(meta.get("plant_name", ""))}">'
    )
    # Metadata
    lines.append("  <metadata>")
    lines.append(
        f'    <design_flow units="m3/d">{_xe(meta.get("design_flow_m3d", ""))}</design_flow>'
    )
    lines.append(
        f'    <temperature units="C">{_xe(meta.get("temperature_C", ""))}</temperature>'
    )
    lines.append(
        f'    <created>{_xe(meta.get("created", datetime.now(timezone.utc).isoformat()))}</created>'
    )
    lines.append(
        f'    <modified>{_xe(meta.get("modified", datetime.now(timezone.utc).isoformat()))}</modified>'
    )
    lines.append(
        f'    <source_generator>{_xe(schematic.get("generator", "wwtp-schematic-builder"))}</source_generator>'
    )
    lines.append("  </metadata>")

    # Units
    lines.append("  <units>")
    for u in units:
        pos = u.get("position", {}) or {}
        lines.append(
            f'    <unit id="{_xe(u.get("id"))}" type="{_xe(u.get("type"))}" '
            f'name="{_xe(u.get("name"))}" '
            f'sumo_template="{_xe(u.get("sumo_template"))}" '
            f'sumo_unit_class="{_xe(u.get("sumo_unit_class"))}">'
        )
        lines.append(
            f'      <position x="{_xe(pos.get("x", 0))}" y="{_xe(pos.get("y", 0))}"/>'
        )
        params = u.get("parameters") or []
        if isinstance(params, dict):
            params = [{"key": k, "value": v} for k, v in params.items()]
        for p in params:
            lines.append(
                f'      <parameter key="{_xe(p.get("key"))}" '
                f'sumo_variable="{_xe(p.get("sumo_variable", ""))}" '
                f'value="{_xe(p.get("value"))}" '
                f'unit="{_xe(p.get("unit", ""))}">'
                f'{_xe(p.get("description", ""))}</parameter>'
            )
        lines.append("    </unit>")
    lines.append("  </units>")

    # Connections
    lines.append("  <connections>")
    for s in streams:
        lines.append(
            f'    <connection id="{_xe(s.get("id"))}" type="{_xe(s.get("type"))}" '
            f'from="{_xe(s.get("from"))}" to="{_xe(s.get("to"))}" '
            f'label="{_xe(s.get("label", ""))}"/>'
        )
    lines.append("  </connections>")

    # Global parameters (placeholder)
    glob = schematic.get("global_params", {}) or {}
    lines.append("  <parameters>")
    for k, v in glob.items():
        lines.append(f'    <parameter key="{_xe(k)}" value="{_xe(v)}"/>')
    lines.append("  </parameters>")
    lines.append("</sumoproject>")
    return "\n".join(lines) + "\n"


def build_state_xml(schematic: dict) -> str:
    """Render an initial-state XML — one <variable> entry per sumo_variable
    found in the schematic. SUMO uses this as the steady-state baseline."""
    meta = schematic.get("meta", {}) or {}
    units = schematic.get("units", []) or []
    lines: list[str] = []
    lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    lines.append(
        f'<state generator="sumo24-mcp sumo_compiler" plant="{_xe(meta.get("plant_name", ""))}">'
    )
    for u in units:
        params = u.get("parameters") or []
        if isinstance(params, dict):
            params = [{"key": k, "value": v} for k, v in params.items()]
        for p in params:
            sv = p.get("sumo_variable")
            if sv:
                lines.append(
                    f'  <variable name="{_xe(sv)}" value="{_xe(p.get("value"))}" '
                    f'unit="{_xe(p.get("unit", ""))}" owner="{_xe(u.get("id"))}"/>'
                )
    lines.append("</state>")
    return "\n".join(lines) + "\n"


def build_metadata_json(schematic: dict) -> str:
    """Render a metadata.json with summary + provenance info."""
    summary = _schp.summarise(schematic)
    meta = schematic.get("meta", {}) or {}
    out = {
        "format": "sumo-project",
        "schema_version": schematic.get("schema_version", "1.0"),
        "generator": "sumo24-mcp sumo_compiler",
        "source_generator": schematic.get("generator", "wwtp-schematic-builder"),
        "compiled_at": datetime.now(timezone.utc).isoformat(),
        "plant_name": meta.get("plant_name", ""),
        "design_flow_m3d": meta.get("design_flow_m3d"),
        "temperature_C": meta.get("temperature_C"),
        "summary": summary,
        "unit_ids": [u.get("id") for u in (schematic.get("units") or [])],
        "stream_ids": [s.get("id") for s in (schematic.get("streams") or [])],
    }
    return json.dumps(out, indent=2)


# ── BUILD / PACKAGE ──────────────────────────────────────────────────────


def preview_sumo_files(schematic: dict, include_sumoslang: bool = True) -> dict[str, str]:
    """Return the rendered text of each file that WOULD go into the .sumo zip."""
    out = {
        "manifest.xml": build_manifest_xml(schematic),
        "state.xml":    build_state_xml(schematic),
        "metadata.json": build_metadata_json(schematic),
    }
    if include_sumoslang:
        out["sumoslang.txt"] = _schp.schematic_to_sumoslang(schematic)
    return out


def compile_to_sumo(
    schematic: dict,
    output_path: str | Path,
    *,
    overwrite: bool = False,
    include_sumoslang: bool = True,
    attach_dll: str | Path | None = None,
) -> dict:
    """Compile a schematic to a .sumo zip file on disk.

    Args:
        schematic:        validated schematic dict
        output_path:      where to write the .sumo file (extension auto-fixed)
        overwrite:        if False and the target exists, returns an error
        include_sumoslang: also bundle the SumoSlang skeleton text
        attach_dll:       optional path to a sumoproject.dll to copy alongside

    Returns a dict with keys: ok, output_path, files_written, attached_dll,
    summary, bytes, errors.
    """
    out = Path(output_path)
    if out.suffix.lower() != ".sumo":
        out = out.with_suffix(".sumo")
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists() and not overwrite:
        return {
            "ok": False,
            "error": f"target exists: {out} (pass overwrite=true to replace)",
            "output_path": str(out),
        }

    # Validate before building
    v = _schp.validate_schematic(schematic)
    if v["errors"]:
        return {
            "ok": False,
            "error": "Schematic has validation errors; aborting compile.",
            "validation": v,
            "output_path": str(out),
        }

    files = preview_sumo_files(schematic, include_sumoslang=include_sumoslang)
    try:
        with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for name, body in files.items():
                zf.writestr(name, body.encode("utf-8"))
    except Exception as e:
        return {"ok": False, "error": f"zip write failed: {e}", "output_path": str(out)}

    result = {
        "ok": True,
        "output_path": str(out),
        "files_written": list(files.keys()),
        "bytes": out.stat().st_size,
        "summary": _schp.summarise(schematic),
        "validation": v,
        "attached_dll": None,
    }

    if attach_dll:
        src = Path(attach_dll)
        if not src.exists():
            result["attached_dll"] = {"ok": False, "error": f"source DLL not found: {src}"}
        else:
            dst = out.with_name("sumoproject.dll")
            try:
                shutil.copy2(src, dst)
                result["attached_dll"] = {"ok": True, "source": str(src), "target": str(dst),
                                          "bytes": dst.stat().st_size}
            except Exception as e:
                result["attached_dll"] = {"ok": False, "error": str(e)}

    # Final cross-check: the file we just wrote should be a valid zip
    result["is_valid_zip"] = zipfile.is_zipfile(out)
    return result


def build_from_html(
    html_path: str | Path,
    output_path: str | Path,
    *,
    overwrite: bool = False,
    include_sumoslang: bool = True,
    attach_dll: str | Path | None = None,
) -> dict:
    """End-to-end pipeline: HTML file → schematic JSON → .sumo zip.

    Reads the embedded <script id="schematic-data"> block from the HTML,
    validates, and compiles to a .sumo file in one call.
    """
    try:
        schematic = _schp.load_schematic(html_path)
    except Exception as e:
        return {"ok": False, "error": f"could not load schematic from HTML: {e}",
                "html_path": str(html_path)}
    return compile_to_sumo(
        schematic, output_path,
        overwrite=overwrite,
        include_sumoslang=include_sumoslang,
        attach_dll=attach_dll,
    )


# ── INSPECTION / VERIFICATION ────────────────────────────────────────────


def read_sumo_manifest(sumo_path: str | Path) -> dict:
    """Open a .sumo zip and pull out the manifest as a parsed dict."""
    p = Path(sumo_path)
    if not p.exists():
        return {"ok": False, "error": f"not found: {p}"}
    if not zipfile.is_zipfile(p):
        return {"ok": False, "error": f"not a zip container: {p}"}
    try:
        with zipfile.ZipFile(p, "r") as zf:
            names = zf.namelist()
            if "manifest.xml" not in names:
                return {"ok": False, "error": "manifest.xml missing inside .sumo zip",
                        "members": names}
            manifest_text = zf.read("manifest.xml").decode("utf-8", errors="replace")
            metadata = {}
            if "metadata.json" in names:
                try:
                    metadata = json.loads(zf.read("metadata.json").decode("utf-8"))
                except Exception:
                    metadata = {}
            state_text = ""
            if "state.xml" in names:
                state_text = zf.read("state.xml").decode("utf-8", errors="replace")
    except Exception as e:
        return {"ok": False, "error": f"zip read failed: {e}"}

    # Parse manifest XML — best-effort, just count units/connections
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(manifest_text)
        units = root.findall("./units/unit")
        conns = root.findall("./connections/connection")
        unit_ids = [u.attrib.get("id") for u in units]
        conn_ids = [c.attrib.get("id") for c in conns]
    except Exception as e:
        return {"ok": False, "error": f"manifest XML parse failed: {e}",
                "manifest_text_sample": manifest_text[:500]}

    return {
        "ok": True,
        "sumo_path": str(p),
        "members": names,
        "unit_count": len(units),
        "connection_count": len(conns),
        "unit_ids": unit_ids,
        "connection_ids": conn_ids,
        "metadata": metadata,
        "state_present": bool(state_text),
        "state_variable_count": state_text.count("<variable ") if state_text else 0,
    }


def verify_against_schematic(sumo_path: str | Path, schematic: dict) -> dict:
    """Compare a .sumo file to the original schematic dict — find drift."""
    sumo_info = read_sumo_manifest(sumo_path)
    if not sumo_info.get("ok"):
        return sumo_info
    sch_units    = {u.get("id") for u in (schematic.get("units")   or [])}
    sch_streams  = {s.get("id") for s in (schematic.get("streams") or [])}
    sumo_units   = set(sumo_info.get("unit_ids") or [])
    sumo_streams = set(sumo_info.get("connection_ids") or [])

    missing_units    = sorted(sch_units    - sumo_units)
    extra_units      = sorted(sumo_units   - sch_units)
    missing_streams  = sorted(sch_streams  - sumo_streams)
    extra_streams    = sorted(sumo_streams - sch_streams)
    return {
        "ok": not (missing_units or extra_units or missing_streams or extra_streams),
        "sumo_path": str(sumo_path),
        "schematic_units": len(sch_units),
        "schematic_streams": len(sch_streams),
        "sumo_units": len(sumo_units),
        "sumo_streams": len(sumo_streams),
        "missing_units_in_sumo": missing_units,
        "extra_units_in_sumo": extra_units,
        "missing_streams_in_sumo": missing_streams,
        "extra_streams_in_sumo": extra_streams,
    }


def attach_companion_dll(sumo_path: str | Path, source_dll: str | Path) -> dict:
    """Copy a sumoproject.dll alongside a .sumo file (overwrites)."""
    sp = Path(sumo_path)
    src = Path(source_dll)
    if not sp.exists():
        return {"ok": False, "error": f"sumo file not found: {sp}"}
    if not src.exists():
        return {"ok": False, "error": f"source DLL not found: {src}"}
    target = sp.with_name("sumoproject.dll")
    try:
        shutil.copy2(src, target)
    except Exception as e:
        return {"ok": False, "error": f"copy failed: {e}"}
    return {"ok": True, "source": str(src), "target": str(target),
            "bytes": target.stat().st_size}
