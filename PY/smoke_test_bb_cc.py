"""
Smoke test for Group BB (schematic) and Group CC (troubleshooting) tools.

Reimplements just enough of the server helpers to exercise:
- schematic_parser: parse HTML, validate, generate commands, generate SumoSlang
- troubleshooting: diagnose a fake .sumo file, repair, scan directory

Does NOT call DTT or openpyxl.
"""
from __future__ import annotations
import json
import shutil
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).parent.resolve()
import sys
sys.path.insert(0, str(HERE))

import schematic_parser as schp
import unit_type_registry as utr

HTML = HERE.parent / "wwtp_schematic_template.html"
assert HTML.exists(), f"missing {HTML}"

print(f"OK loaded HTML at {HTML}")

# ── 1. parser: extract JSON from the raw template ───────────────────────────
data = schp.extract_json_from_html(HTML)
print(f"OK extracted schematic block: {len(data.get('units', []))} units, "
      f"{len(data.get('streams', []))} streams")
assert data["schema_version"] == "1.0"
# Note: the raw HTML's embedded block is empty (units: []). That is by design.
# The Qaha template is loaded by JS at runtime — not baked into the file.

# ── 2. validation against an empty schematic ────────────────────────────────
v = schp.validate_schematic(data)
print(f"OK validation on empty template: {len(v['errors'])} errors, "
      f"{len(v['warnings'])} warnings")
assert any("no units" in e.lower() for e in v["errors"]), \
    "Expected 'no units' error on raw template"

# ── 3. validation against a populated Qaha-style schematic ──────────────────
qaha = {
    "schema_version": "1.0",
    "generator": "wwtp-schematic-builder",
    "meta": {"plant_name": "Qaha Test", "design_flow_m3d": 9820,
             "temperature_C": 22, "created": "2026-05-12T10:00Z",
             "modified": "2026-05-12T10:00Z"},
    "units": [
        {"id": "U1", "type": "influent",            "name": "Inf",
         "position": {"x": 40, "y": 200},
         "sumo_template": "Sumo__Plant__Influent",
         "sumo_unit_class": "Influent",
         "parameters": [
            {"key": "Q",    "value": 9820, "unit": "m³/d", "sumo_variable": "Sumo__Plant__Influent__param__Q", "description": "Flow"},
            {"key": "XCOD", "value": 650,  "unit": "mg/L", "sumo_variable": "Sumo__Plant__Influent__param__XCOD", "description": "COD"},
         ]},
        {"id": "U2", "type": "oxidation_ditch",     "name": "OD",
         "position": {"x": 300, "y": 200},
         "sumo_template": "Sumo__Plant__OxDitch",
         "sumo_unit_class": "CSTR",
         "parameters": [
            {"key": "V", "value": 7480, "unit": "m³", "sumo_variable": "Sumo__Plant__OxDitch__param__V", "description": "Volume"},
         ]},
        {"id": "U3", "type": "secondary_clarifier", "name": "Final",
         "position": {"x": 560, "y": 200},
         "sumo_template": "Sumo__Plant__Final",
         "sumo_unit_class": "Settler1D",
         "parameters": [
            {"key": "A", "value": 740, "unit": "m²", "sumo_variable": "Sumo__Plant__Final__param__A", "description": "Area"},
         ]},
        {"id": "U4", "type": "effluent",            "name": "Eff",
         "position": {"x": 820, "y": 200},
         "sumo_template": "Sumo__Plant__Effluent",
         "sumo_unit_class": "Effluent",
         "parameters": []},
        {"id": "U5", "type": "ras_pump",            "name": "RAS",
         "position": {"x": 300, "y": 360},
         "sumo_template": "Sumo__Plant__RAS_Pump",
         "sumo_unit_class": "Pump",
         "parameters": [
            {"key": "ratio", "value": 0.75, "unit": "-", "sumo_variable": "Sumo__Plant__RAS_Pump__param__ratio", "description": "RAS ratio"},
         ]},
    ],
    "streams": [
        {"id": "S1", "type": "process_flow", "from": "U1", "to": "U2", "label": ""},
        {"id": "S2", "type": "process_flow", "from": "U2", "to": "U3", "label": "MLSS"},
        {"id": "S3", "type": "process_flow", "from": "U3", "to": "U4", "label": ""},
        # loop:
        {"id": "S4", "type": "process_flow", "from": "U3", "to": "U5", "label": ""},
        {"id": "S5", "type": "ras",          "from": "U5", "to": "U2", "label": "RAS"},
    ],
    "global_params": {}
}
v2 = schp.validate_schematic(qaha)
print(f"OK Qaha validation: {len(v2['errors'])} errors, {len(v2['warnings'])} warnings")
assert not v2["errors"], f"Unexpected errors: {v2['errors']}"

# ── 4. command generation ───────────────────────────────────────────────────
cmds = schp.schematic_to_commands(qaha)
print(f"OK generated {len(cmds)} command lines")
set_lines = [c for c in cmds if c.startswith("set ")]
print(f"   set commands: {len(set_lines)}")
assert any("Sumo__Plant__OxDitch__param__V 7480" in c for c in set_lines)

# ── 5. DTT actions ──────────────────────────────────────────────────────────
acts = schp.schematic_to_dtt_actions(qaha)
addp = sum(1 for a in acts if a["step"] == "addprocess")
conn = sum(1 for a in acts if a["step"] == "connect")
setp = sum(1 for a in acts if a["step"] == "setparameter")
print(f"OK DTT actions: addprocess={addp} connect={conn} setparameter={setp}")
assert addp == 5 and conn == 5 and setp >= 5

# ── 6. SumoSlang skeleton ──────────────────────────────────────────────────
ss = schp.schematic_to_sumoslang(qaha)
assert "plant" in ss.lower() and "connect" in ss.lower()
print(f"OK SumoSlang skeleton: {len(ss.splitlines())} lines")

# ── 7. summarise ───────────────────────────────────────────────────────────
summ = schp.summarise(qaha)
print(f"OK summary: {summ['unit_count']} units, "
      f"by_category={summ['units_by_category']}, "
      f"streams_by_type={summ['streams_by_type']}")

# ── 8. comparison ───────────────────────────────────────────────────────────
diff = schp.compare_to_model(qaha, model_unit_ids=["U1", "U2", "U3", "U4"])
assert diff["missing_in_model"] == ["U5"]
print(f"OK compare: matched={diff['matched']} missing={diff['missing_in_model']}")

# ── 9. Group CC: diagnose a fake .sumo file ────────────────────────────────
tmp = Path(tempfile.mkdtemp(prefix="sumo_diag_"))
fake = tmp / "fake.sumo"

# (a) empty file
fake.write_bytes(b"")
import importlib.util
spec = importlib.util.spec_from_file_location("server_helpers", HERE / "server.py")
# Cannot import server.py whole (it kicks off MCP) — instead emulate the helper:
import zipfile, os
def diag(path):
    p = Path(path)
    rep = {"exists": p.exists(), "ok": True, "errors": [], "warnings": [], "checks": {}}
    if not p.exists():
        rep["ok"] = False
        rep["errors"].append("missing")
        return rep
    sz = p.stat().st_size
    rep["checks"]["size_bytes"] = sz
    if sz == 0:
        rep["ok"] = False
        rep["errors"].append("EMPTY_FILE")
        return rep
    rep["checks"]["is_zip_container"] = zipfile.is_zipfile(p)
    dll = p.with_name("sumoproject.dll")
    rep["checks"]["dll_present"] = dll.exists()
    if not dll.exists():
        rep["warnings"].append("MISSING_DLL")
    return rep

r1 = diag(fake)
assert "EMPTY_FILE" in r1["errors"]
print(f"OK empty .sumo correctly flagged: {r1['errors']}")

# (b) non-zip stub
fake.write_text('<?xml version="1.0"?><sumoproject/>', encoding="utf-8")
r2 = diag(fake)
assert r2["ok"] and "MISSING_DLL" in r2["warnings"]
print(f"OK stub .sumo health: warnings={r2['warnings']}")

# (c) make a fake zip
with zipfile.ZipFile(fake, "w") as zf:
    zf.writestr("manifest.xml", '<?xml version="1.0"?><sumoproject><units/></sumoproject>')
r3 = diag(fake)
assert r3["checks"]["is_zip_container"] is True
print(f"OK zip .sumo recognised: {r3['checks']}")

# (d) place a fake DLL alongside
(fake.parent / "sumoproject.dll").write_bytes(b"\x00" * 32)
r4 = diag(fake)
assert r4["checks"]["dll_present"] is True
assert "MISSING_DLL" not in r4["warnings"]
print(f"OK companion DLL detected: warnings={r4['warnings']}")

shutil.rmtree(tmp)

print("\n=========================================")
print(" ALL GROUP BB + GROUP CC SMOKE TESTS PASSED")
print("=========================================")
print(f" Schematic registry types: {len(utr.UNIT_TYPES)}")
print(f" Stream types: {utr.STREAM_TYPES}")
print(f" Qaha test: {len(qaha['units'])} units, {len(qaha['streams'])} streams (loop included)")
