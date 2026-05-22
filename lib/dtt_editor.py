"""
dtt_editor.py  —  Group FF support module (SUMO24 MCP)

Pure-stdlib. NO direct DTT import — DTT is dispatched from the server's
_exp_* wrappers (which already own the _make_ds() bridge). This module's job
is to:

  * generate vetted DTT command strings,
  * manage edit-transaction state.xml snapshots on disk,
  * diff a live manifest summary against the .sumo file on disk.

Every public function returns a plain dict; the server wraps it in the
project's JSON return envelope.
"""

from __future__ import annotations
import datetime as _dt
import json
import os
import shutil
import zipfile
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# DTT command builders — pure string assembly, no execution.
# These follow the SumoCore convention used everywhere else in the server:
#     Sumo__Plant__<UnitName>__param__<suffix>
# Cowork: if the live DTT exposes different verbs (e.g. `renameUnit` vs
# `rename`), adjust ONLY the right-hand strings in _DTT_VERBS below.
# ---------------------------------------------------------------------------
_DTT_VERBS = {
    "rename_unit":       "renameUnit",        # ds.sumo.executeCommand("renameUnit X Y")
    "change_unit_class": "changeUnitClass",   # "changeUnitClass <unit> <new_class>"
    "remove_stream":     "removeStream",      # "removeStream <stream_id>"
    "set_stream_q":      "setStreamFlow",     # "setStreamFlow <stream_id> <Q>"
    "remove_controller": "removeController",  # "removeController <ctrl_id>"
}

def cmd_rename_unit(old: str, new: str) -> str:
    _require_ident(old, "old unit name")
    _require_ident(new, "new unit name")
    return f'{_DTT_VERBS["rename_unit"]} {old} {new}'

def cmd_change_unit_type(unit: str, new_class: str) -> str:
    _require_ident(unit, "unit name")
    _require_ident(new_class, "new class")
    return f'{_DTT_VERBS["change_unit_class"]} {unit} {new_class}'

def cmd_remove_stream(stream_id: str) -> str:
    _require_ident(stream_id, "stream id")
    return f'{_DTT_VERBS["remove_stream"]} {stream_id}'

def cmd_set_stream_flow(stream_id: str, q_m3d: float) -> str:
    _require_ident(stream_id, "stream id")
    if q_m3d is None:
        raise ValueError("q_m3d is required")
    return f'{_DTT_VERBS["set_stream_q"]} {stream_id} {float(q_m3d)}'

def cmd_remove_controller(ctrl_id: str) -> str:
    _require_ident(ctrl_id, "controller id")
    return f'{_DTT_VERBS["remove_controller"]} {ctrl_id}'

def cmds_modify_controller(ctrl_id: str,
                           setpoint: Optional[float] = None,
                           gain: Optional[float] = None,
                           integral_time: Optional[float] = None,
                           output_min: Optional[float] = None,
                           output_max: Optional[float] = None) -> List[str]:
    """Controllers expose tunable parameters as SumoCore variables; we just
    set them. The exact suffixes can vary by controller class — common ones
    are SP/Kp/Ti/uMin/uMax. Adjust _CTRL_SUFFIX if your build uses different
    names; this is the only place that matters."""
    _require_ident(ctrl_id, "controller id")
    out: List[str] = []
    mapping = (
        ("SP",   setpoint),
        ("Kp",   gain),
        ("Ti",   integral_time),
        ("uMin", output_min),
        ("uMax", output_max),
    )
    for sfx, val in mapping:
        if val is None:
            continue
        out.append(
            f"set Sumo__Plant__{ctrl_id}__param__{sfx} {float(val)}")
    if not out:
        raise ValueError("No controller field provided to modify.")
    return out

# ---------------------------------------------------------------------------
# Edit-transaction primitives (state.xml snapshot ring).
# Snapshots live alongside the active state.xml; commit retires them; rollback
# replaces state.xml with the snapshot. Pure file ops — DTT is reset in the
# server wrapper via initialize_state-like behaviour after a rollback.
# ---------------------------------------------------------------------------
def tx_begin(state_xml_path: str, label: str = "edit") -> Dict[str, Any]:
    if not os.path.isfile(state_xml_path):
        return {"ok": False, "error": f"state.xml not found at {state_xml_path}"}
    ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = _slug(label)
    snap = f"{state_xml_path}.tx_{ts}_{safe}.bak"
    shutil.copy2(state_xml_path, snap)
    tx_id = os.path.basename(snap)
    return {"ok": True, "tx_id": tx_id, "snapshot_path": snap,
            "state_xml": state_xml_path, "label": label, "created": ts}

def tx_list(state_xml_path: str) -> Dict[str, Any]:
    folder = os.path.dirname(state_xml_path) or "."
    base = os.path.basename(state_xml_path)
    snaps: List[Dict[str, Any]] = []
    if os.path.isdir(folder):
        for fn in sorted(os.listdir(folder)):
            if fn.startswith(base + ".tx_") and fn.endswith(".bak"):
                full = os.path.join(folder, fn)
                snaps.append({"tx_id": fn,
                              "snapshot_path": full,
                              "size_bytes": os.path.getsize(full),
                              "mtime": _dt.datetime.fromtimestamp(
                                  os.path.getmtime(full)).isoformat()})
    return {"transactions": snaps, "count": len(snaps)}

def tx_commit(state_xml_path: str, tx_id: str,
              keep_snapshot: bool = False) -> Dict[str, Any]:
    snap = _resolve_snapshot(state_xml_path, tx_id)
    if not snap:
        return {"ok": False, "error": f"tx_id not found: {tx_id}"}
    if not keep_snapshot:
        try:
            os.remove(snap)
            return {"ok": True, "tx_id": tx_id, "snapshot_removed": True}
        except OSError as e:
            return {"ok": False, "error": f"could not remove snapshot: {e!r}"}
    return {"ok": True, "tx_id": tx_id, "snapshot_kept": snap}

def tx_rollback(state_xml_path: str, tx_id: str) -> Dict[str, Any]:
    snap = _resolve_snapshot(state_xml_path, tx_id)
    if not snap:
        return {"ok": False, "error": f"tx_id not found: {tx_id}"}
    try:
        # also back up the current state.xml before overwriting it
        ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        side = f"{state_xml_path}.preRollback_{ts}.bak"
        if os.path.isfile(state_xml_path):
            shutil.copy2(state_xml_path, side)
        shutil.copy2(snap, state_xml_path)
        return {"ok": True, "restored_from": snap,
                "previous_state_backup": side,
                "note": "Re-initialise the DTT state in the server wrapper "
                        "(initialize_state) so in-memory matches disk."}
    except OSError as e:
        return {"ok": False, "error": f"rollback failed: {e!r}"}

def _resolve_snapshot(state_xml_path: str, tx_id: str) -> Optional[str]:
    folder = os.path.dirname(state_xml_path) or "."
    full = os.path.join(folder, tx_id)
    return full if os.path.isfile(full) else None

# ---------------------------------------------------------------------------
# Batch dispatcher — validation + structured planning only; the server runs
# the commands.
# ---------------------------------------------------------------------------
_FORBIDDEN_TOKENS = ("rm ", "del ", ";", "&&", "|", "exec(", "eval(")

def plan_command_batch(commands: List[str],
                       allow_raw: bool = False) -> Dict[str, Any]:
    """Vet a list of DTT command strings. Returns a plan the server can
    dispatch with ds.sumo.executeCommand(line) per entry."""
    if not isinstance(commands, list) or not commands:
        return {"ok": False, "error": "commands must be a non-empty list"}
    cleaned: List[str] = []
    rejected: List[Dict[str, str]] = []
    for raw in commands:
        if not isinstance(raw, str):
            rejected.append({"command": repr(raw), "reason": "not a string"})
            continue
        line = raw.strip()
        if not line:
            continue
        if not allow_raw:
            low = line.lower()
            bad = next((t for t in _FORBIDDEN_TOKENS if t in low), None)
            if bad:
                rejected.append({"command": line,
                                 "reason": f"forbidden token {bad!r}; "
                                           f"set allow_raw=True to override"})
                continue
            # Sanity: every safe line should look like 'set ...' or be a known
            # DTT verb. Otherwise flag for human review.
            first = line.split(" ", 1)[0]
            known = first == "set" or first in _DTT_VERBS.values()
            if not known:
                rejected.append({"command": line,
                                 "reason": f"unknown verb {first!r}; "
                                           f"set allow_raw=True to override"})
                continue
        cleaned.append(line)
    return {"ok": bool(cleaned), "planned": cleaned,
            "rejected": rejected, "count": len(cleaned),
            "rejected_count": len(rejected)}

# ---------------------------------------------------------------------------
# in-memory <-> disk diff (manifest level)
# ---------------------------------------------------------------------------
def diff_units_streams(live_units: List[str],
                       live_streams: List[str],
                       manifest_summary: Dict[str, Any]) -> Dict[str, Any]:
    """live_* come from list_unit_processes / list_flow_streams in-memory.
    manifest_summary is what sumo_compiler.read_sumo_manifest() returns."""
    disk_units = set(manifest_summary.get("unit_ids")
                     or manifest_summary.get("units") or [])
    disk_streams = set(manifest_summary.get("stream_ids")
                       or manifest_summary.get("connections") or [])
    live_u = set(live_units or [])
    live_s = set(live_streams or [])
    units_only_live = sorted(live_u - disk_units)
    units_only_disk = sorted(disk_units - live_u)
    streams_only_live = sorted(live_s - disk_streams)
    streams_only_disk = sorted(disk_streams - live_s)
    in_sync = not any([units_only_live, units_only_disk,
                       streams_only_live, streams_only_disk])
    return {"in_sync": in_sync,
            "units_only_in_memory": units_only_live,
            "units_only_on_disk":   units_only_disk,
            "streams_only_in_memory": streams_only_live,
            "streams_only_on_disk":   streams_only_disk,
            "live_unit_count":   len(live_u),
            "disk_unit_count":   len(disk_units),
            "live_stream_count": len(live_s),
            "disk_stream_count": len(disk_streams)}

# ---------------------------------------------------------------------------
# manifest helpers (read-only on the .sumo zip)
# ---------------------------------------------------------------------------
def read_controllers_from_manifest(sumo_path: str) -> Dict[str, Any]:
    """Best-effort enumeration of <controller> entries in manifest.xml.
    Used as a fallback when DTT does not expose a controller-list API."""
    if not os.path.isfile(sumo_path):
        return {"ok": False, "error": f".sumo not found: {sumo_path}"}
    out: List[Dict[str, Any]] = []
    try:
        with zipfile.ZipFile(sumo_path, "r") as zf:
            if "manifest.xml" not in zf.namelist():
                return {"ok": False, "error": "manifest.xml missing in .sumo"}
            with zf.open("manifest.xml") as fh:
                tree = ET.parse(fh)
        root = tree.getroot()
        for c in root.iter():
            tag = c.tag.lower()
            if "controller" in tag:
                rec = {"tag": c.tag}
                rec.update({k: v for k, v in c.attrib.items()})
                out.append(rec)
    except (zipfile.BadZipFile, ET.ParseError) as e:
        return {"ok": False, "error": f"manifest parse failed: {e!r}"}
    return {"ok": True, "controllers": out, "count": len(out)}

# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
def _require_ident(s: Any, label: str) -> None:
    if not isinstance(s, str) or not s.strip():
        raise ValueError(f"{label} must be a non-empty string")
    if any(ch in s for ch in (" ", "\t", "\n", ";", "|", "&")):
        raise ValueError(f"{label} contains forbidden whitespace/shell char: {s!r}")

def _slug(s: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in str(s))[:40] or "tx"
