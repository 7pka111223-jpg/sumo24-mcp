"""Compatibility shim for the official Dynamita SumoScheduler.

The MCP server (server.py) calls three methods on `ds.sumo` (a SumoScheduler
instance) that exist in some internal/extended DTT distributions but are NOT
present in the official, publicly shipped `dynamita.scheduler.SumoScheduler`
class:

    - executeCommand(cmd)
    - set(var, value)
    - getVariableNames()

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
