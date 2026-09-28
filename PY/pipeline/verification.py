"""Truthful compatibility evidence gate; symbol inspection is not runtime validation."""
from pathlib import Path
import hashlib
import json


def verify_stage8(dll_result: dict, schematic_path: str, dll_path: str,
                  state_xml: str, evidence_path: str = "") -> dict:
    """Require matching artifact hashes from a successful native validation run."""
    errors = []
    paths = {"schematic": Path(schematic_path), "dll": Path(dll_path), "state": Path(state_xml)}
    for name, path in paths.items():
        if not path.is_file():
            errors.append(f"{name} file is required")
    if not dll_result.get("ok") or dll_result.get("mode") == "exports_only":
        errors.append("DLL inspection is not schematic compatibility verification")
    if not isinstance(dll_result.get("refs_resolved"), int) or dll_result.get("refs_resolved", 0) <= 0:
        errors.append("No meaningful schematic references were verified")
    try:
        evidence = json.loads(Path(evidence_path).read_text(encoding="utf-8")) if evidence_path else {}
    except (OSError, ValueError):
        evidence = {}
    if evidence.get("status") != "completed" or evidence.get("runtime_validation") is not True:
        errors.append("Successful native model/state validation evidence is required")
    for name, path in paths.items():
        if path.is_file() and evidence.get(f"{name}_sha256") != hashlib.sha256(path.read_bytes()).hexdigest():
            errors.append(f"{name} identity does not match validation evidence")
    return {"ok": not errors, "status": "verified" if not errors else "not_verified",
            "errors": errors, "runtime_validated": not errors}
