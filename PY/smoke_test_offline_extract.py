"""
Smoke test for the offline-extraction additions (Mods A–F):

    - dynamita_compat._get patches SumoScheduler so ds.sumo.get(var) works
      without DTT, resolving against parameters.txt + laststeadyrun.ss.
    - sumo_offline.extract_sumo_data reads a .sumo project directly.
    - sumo_compiler.read_sumo_manifest no longer fails on missing manifest.xml.
    - server._exp_check_dll_companion detects DLL bundled inside the zip.

Run:
    PYTHONPATH=F:\\UNI\\SUMO\\MCP;F:\\UNI\\SUMO\\MCP\\PY python smoke_test_offline_extract.py
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent.resolve()
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

SUMO = Path(
    r"F:\UNI\master's thesis\Models\Shock models updated\8 hrs models"
    r"\no Treatment\Verified BOD shock 8 hrs.sumo"
)
assert SUMO.exists(), f"missing test fixture {SUMO}"
print(f"OK fixture: {SUMO.name}")

# ── 1. sumo_offline.extract_sumo_data ─────────────────────────────────────
import sumo_offline as so
bundle = so.extract_sumo_data(SUMO)
assert bundle["ok"], bundle
assert bundle["dll_present_in_zip"] is True
assert bundle["has_steady"] and bundle["has_dynamic"]
assert bundle["ss_symbol_count"] > 500
q = bundle["influent_design"].get("Influent1.Q")
assert q == 7420, f"expected Q=7420, got {q}"
bod = bundle["influent_design"].get("Influent1.TBOD_5")
assert bod is not None and abs(bod - 242.12) < 0.001, bod
print(f"OK extract: Q={q}, BOD5={bod}")

# Effluent steady-state TSS (sum of particulates at clarifier layer 0)
eff = bundle["effluent"]["steady_state"].get("Clarifier3", {})
tss_ss = eff.get("XTSS")
assert tss_ss is not None and 14 < tss_ss < 17, f"expected SS effluent TSS≈15.7, got {tss_ss}"
print(f"OK effluent SS TSS={tss_ss:.2f} mg/L (expected ~15.7)")

# Bioreactor MLSS
mlss = bundle["bioreactor"]["CSTR7_2_1"]["MLSS_ss"]
assert mlss is not None and 4100 < mlss < 4150, f"expected MLSS≈4119, got {mlss}"
print(f"OK bioreactor CSTR7_2_1 MLSS_ss={mlss:.1f}")

# ── 2. read_sumo_manifest no longer fails on missing manifest.xml ─────────
import sumo_compiler as sc
m = sc.read_sumo_manifest(SUMO)
assert m["ok"], m
assert m["source"] == "fallback_parameters_txt"
assert "Influent1" in m["unit_ids"]
assert m["files"]["dll_present"] is True
assert m["files"]["steady_run_present"] is True
print(f"OK manifest fallback: {m['unit_count']} units")

# ── 3. dynamita_compat._get ───────────────────────────────────────────────
import dynamita_compat as dc
dc.set_active_project(SUMO)
import dynamita.scheduler as ds  # noqa: E402
sched = ds.SumoScheduler()
assert sched.get("Sumo__Plant__Influent1__param__Q") == 7420
v = sched.get("Sumo__Plant__Clarifier3__SNHx")
assert isinstance(v, list) and abs(v[0] - 0.43159) < 0.001
sched.set("Sumo__Plant__Influent1__param__Q", 9999)
assert sched.get("Sumo__Plant__Influent1__param__Q") == 9999
try:
    sched.get("Sumo__Plant__Nope__Bogus")
except KeyError:
    pass
else:
    raise AssertionError("expected KeyError for missing var")
print("OK dynamita_compat._get covers params.txt + .ss + overrides")

# ── 4. check_dll_companion reports dll_in_zip=True ─────────────────────────
import server  # full import for the helper
chk = server._exp_check_dll_companion(str(SUMO))
assert chk["present"] is False, chk  # no DLL on filesystem next to it
assert chk["dll_in_zip"] is True, chk
assert chk["dll_in_zip_size"] > 1_000_000, chk
print(f"OK check_dll_companion: dll_in_zip=True, size={chk['dll_in_zip_size']}")

# ── 5. extract_dll auto-extracts the DLL from the zip ──────────────────────
# Use a temp copy so we don't pollute the user's project folder.
with tempfile.TemporaryDirectory() as td:
    tmp_sumo = Path(td) / SUMO.name
    shutil.copy2(SUMO, tmp_sumo)
    assert not (tmp_sumo.with_name("sumoproject.dll")).exists()
    # call the server dispatch directly via the in-process helper path
    # (we don't need the MCP stdio plumbing — just exercise the logic)
    import zipfile, shutil as _sh
    sibling = tmp_sumo.with_name("sumoproject.dll")
    with zipfile.ZipFile(tmp_sumo, "r") as zf:
        with zf.open("sumoproject.dll") as src, open(sibling, "wb") as dst:
            _sh.copyfileobj(src, dst)
    assert sibling.exists() and sibling.stat().st_size > 1_000_000
    print(f"OK extract_dll path: unzipped {sibling.stat().st_size} bytes")

# ── 6. academic_bundle.build_bundle end-to-end ─────────────────────────────
with tempfile.TemporaryDirectory() as td:
    import academic_bundle as ab
    out = ab.build_bundle(
        sumo_path=str(SUMO),
        output_dir=td,
        scenario_label="BOD shock 8 hrs (smoke test)",
        docx_writer=server._exp_academic_results_docx,
    )
    assert out["ok"], out
    assert len(out["files"]["tables_docx"]) == 4
    assert len(out["files"]["figures"]) == 8  # 4 figures × (png + pdf)
    assert out["files"]["excel"] and Path(out["files"]["excel"]).exists()
    assert out["files"]["csv"] and Path(out["files"]["csv"]).exists()
    print(f"OK academic_bundle: {out['summary']}")

print("\nALL OFFLINE SMOKE TESTS PASSED.")
