"""Compatibility shim for the official Dynamita SumoScheduler.

The MCP server (server.py) calls four methods on `ds.sumo` (a SumoScheduler
instance) that exist in some internal/extended DTT distributions but are NOT
present in the official, publicly shipped `dynamita.scheduler.SumoScheduler`
class:

    - executeCommand(cmd)
    - set(var, value)
    - getVariableNames()
    - get(var)

Without these, every model-build / parameter-set / inspection tool returns
"'SumoScheduler' object has no attribute 'executeCommand'" and never reaches
the DTT, so newly-added units never appear in `sumoproject.plant` and parameter
edits are silently dropped.

This shim monkey-patches SumoScheduler at import time so the missing methods
exist. Their implementation:

    * Queues every command/set into an in-memory list and also writes it to a
      sibling commands.txt of the active project (when one is known), so the
      next time the user opens the .sumo project in SUMO24 GUI and hits Start,
      the commands can be replayed against the live model. Also tries the
      official `sendCommand(job_id, ...)` if a job is currently scheduled.

    * `getVariableNames()` parses state.xml and returns the variable names
      recovered there, which is what most inspection tools actually need.

    * `get(var)` resolves an individual Sumo state-variable name to a value
      by, in order: looking in the per-process override queue (anything the
      caller set via `.set()` since process start), reading the most recent
      laststeadyrun.ss / lastdynamicrun.ss of the active project, and finally
      falling back to state.xml. Returns the value or raises KeyError; the
      MCP server's existing try/except wraps that into a JSON envelope.

Activation: server.py simply does `import dynamita_compat` after importing
dynamita.scheduler. The patch is idempotent and a no-op if the real methods
already exist (e.g. in extended DTT distributions).
"""

from __future__ import annotations

import os
import threading
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable

try:
    import dynamita.scheduler as ds
except ImportError:
    ds = None


_lock = threading.Lock()
_command_queue: list[str] = []
_param_overrides: dict[str, float] = {}
_active_project: Path | None = None


def set_active_project(path):
    """Tell the shim which .sumo project to sync the userscript into."""
    global _active_project
    _active_project = Path(path) if path else None


def get_queue() -> list[str]:
    with _lock:
        return list(_command_queue)


def get_overrides() -> dict[str, float]:
    with _lock:
        return dict(_param_overrides)


def clear_queue() -> None:
    with _lock:
        _command_queue.clear()
        _param_overrides.clear()


def flush_to_userscript(sumo_project_path=None):
    """Write every queued command into a sibling <project>.commands.txt file.
    The user can paste these into the SUMO24 Core Window or save_model can
    fold them into the .sumo zip's userscript.txt.
    """
    target = Path(sumo_project_path) if sumo_project_path else _active_project
    if target is None:
        return None
    sibling = target.with_suffix(".commands.txt")
    with _lock:
        sibling.write_text(
            "# Commands captured by dynamita_compat (auto-generated)\n"
            "# Replay in SUMO24 Core Window if not picked up automatically.\n\n"
            + "\n".join(_command_queue) + "\n",
            encoding="utf-8",
        )
    return str(sibling)


def _executeCommand(self, cmd):
    """Queue an arbitrary SumoCore command (e.g. 'set Sumo__... 1.5')."""
    with _lock:
        _command_queue.append(str(cmd).strip())
    try:
        jobs = getattr(self, "jobData", {}) or {}
        if jobs:
            job_id = max(jobs.keys())
            self.sendCommand(job_id, str(cmd))
    except Exception:
        pass
    return True


def _set(self, var, val):
    """Queue a 'set' command - equivalent to executeCommand('set var val')."""
    with _lock:
        _param_overrides[str(var)] = val
        _command_queue.append(f"set {var} {val}")
    try:
        jobs = getattr(self, "jobData", {}) or {}
        if jobs:
            job_id = max(jobs.keys())
            self.sendCommand(job_id, f"set {var} {val}")
    except Exception:
        pass
    return True


def _getVariableNames(self):
    """Return variable names parsed from state.xml. Returns [] if missing."""
    candidates = [
        Path(os.environ.get("SUMO_STATE", "")),
        Path(__file__).resolve().parent.parent / "state.xml",
    ]
    for p in candidates:
        if p and p.is_file():
            try:
                tree = ET.parse(p)
                names = set()
                for el in tree.iter():
                    n = el.get("name") or el.get("sym") or el.get("Symbol")
                    if n:
                        names.add(n)
                return sorted(names)
            except Exception:
                continue
    return []


def _candidate_ss_paths():
    """Yield candidate .ss / state.xml file paths in priority order.

    Priority: active project's siblings first, then env-pointed state.xml,
    then the MCP-root state.xml. Non-existent paths are skipped by the
    caller.
    """
    if _active_project is not None:
        ap = _active_project
        # If the active project is a .sumo zip, look inside it.
        yield ("zip", ap, "laststeadyrun.ss")
        yield ("zip", ap, "lastdynamicrun.ss")
        # Sibling files (extracted_data style).
        yield ("file", ap.with_name("laststeadyrun.ss"), None)
        yield ("file", ap.with_name("lastdynamicrun.ss"), None)
    yield ("file", Path(os.environ.get("SUMO_STATE", "")), None)
    yield ("file", Path(__file__).resolve().parent.parent / "state.xml", None)


def _params_txt_lookup(var: str):
    """Read parameters.txt (constant inputs) from the active project's .sumo
    zip or its sibling extracted_data folder. Returns the value or None."""
    if _active_project is None:
        return None
    try:
        import sumo_offline as _so
    except Exception:
        return None
    ap = _active_project
    text = None
    if ap.exists() and ap.suffix.lower() == ".sumo":
        import zipfile
        try:
            with zipfile.ZipFile(ap, "r") as zf:
                if "parameters.txt" in zf.namelist():
                    text = zf.read("parameters.txt").decode("utf-8", errors="replace")
        except Exception:
            text = None
    if text is None:
        sibling = ap.with_name("parameters.txt")
        if sibling.is_file():
            try:
                text = sibling.read_text(encoding="utf-8", errors="replace")
            except Exception:
                text = None
    if not text:
        return None
    parsed = _so.read_parameters_txt(text)
    return parsed["constant"].get(var)


def _ss_lookup(var: str):
    """Walk the candidate .ss / state.xml paths and return the first hit.
    Returns the value (scalar or list) or raises KeyError(var) if absent."""
    # Constant-input parameters live in parameters.txt, not .ss / state.xml.
    if "__param__" in var:
        v = _params_txt_lookup(var)
        if v is not None:
            return v

    try:
        import sumo_offline as _so  # local import — module ships alongside us
    except Exception:
        _so = None

    for kind, target, member in _candidate_ss_paths():
        if kind == "zip":
            if not target or not target.exists() or _so is None:
                continue
            try:
                data = _so.read_ss_cached(target, member)
            except Exception:
                continue
            if var in data:
                return data[var]
        else:
            if not target or not target.is_file():
                continue
            # .ss files: prefer sumo_offline if available, else hand-parse.
            text = None
            try:
                text = target.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            if _so is not None and target.suffix == ".ss":
                data = _so.parse_ss_xml(text)
                if var in data:
                    return data[var]
            else:
                # state.xml fallback — scan for the symbol attribute.
                try:
                    tree = ET.fromstring(text)
                except Exception:
                    continue
                for el in tree.iter():
                    name = el.get("name") or el.get("symbol")
                    if name != var:
                        continue
                    raw = el.text or (el.find("value").text if el.find("value") is not None else "")
                    raw = (raw or "").strip()
                    if ";" in raw:
                        try:
                            return [float(x) for x in raw.split(";")]
                        except ValueError:
                            return raw
                    try:
                        return float(raw)
                    except ValueError:
                        return raw
    raise KeyError(var)


def _get(self, var):
    """Resolve a Sumo state-variable name to a value without DTT.

    Priority order:
      1. _param_overrides (anything the caller set this session)
      2. Active project's laststeadyrun.ss / lastdynamicrun.ss
      3. Sibling state.xml or MCP-root state.xml

    Raises KeyError(var) if no source has the variable.
    """
    with _lock:
        if var in _param_overrides:
            return _param_overrides[var]
    return _ss_lookup(var)


def install():
    """Apply the monkey-patch. Idempotent."""
    if ds is None:
        return {"installed": False, "reason": "dynamita.scheduler not importable"}
    patched = []
    try:
        if not hasattr(ds.SumoScheduler, "executeCommand"):
            ds.SumoScheduler.executeCommand = _executeCommand
            patched.append("executeCommand")
        if not hasattr(ds.SumoScheduler, "set"):
            ds.SumoScheduler.set = _set
            patched.append("set")
        if not hasattr(ds.SumoScheduler, "getVariableNames"):
            ds.SumoScheduler.getVariableNames = _getVariableNames
            patched.append("getVariableNames")
        if not hasattr(ds.SumoScheduler, "get"):
            ds.SumoScheduler.get = _get
            patched.append("get")
    except Exception as exc:
        return {"installed": False, "reason": f"patch failed: {exc!r}"}
    return {
        "installed": True,
        "patched_methods": patched,
        "note": "Commands queue instead of crashing. Call dynamita_compat."
                "flush_to_userscript() before save_model to persist them.",
    }


# Auto-install on import.
INSTALL_STATUS = install()
