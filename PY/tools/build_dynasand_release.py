"""Maintainer-only build/test/attest command; never run by the user installer."""
from pathlib import Path
import json
import os
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "PY"), str(ROOT)]
import build_provenance
import spec_review
import unit_emitter
import plant_emitter
from sumo_paths import resolve_install_dir

NAME = "HH_DynaSand_v1"
BUNDLES = ROOT / "PY" / "bundled_units"
BUNDLE = BUNDLES / NAME
WORK = ROOT / "docs" / "reviews" / "implementation-2026-09-08" / "dynasand_build"


def prepare():
    original = ROOT / "custom_units" / NAME
    BUNDLE.mkdir(parents=True, exist_ok=True)
    legacy = {p.name: [build_provenance.sha(p)] for p in original.glob("*") if p.suffix in (".xlsx", ".emf")}
    (BUNDLES / "legacy_dynasand.json").write_text(json.dumps(legacy, indent=2), encoding="utf-8")
    spec = json.loads((original / "unit_spec.json").read_text(encoding="utf-8"))
    spec["description"] += "\nSUMO24 MCP units / DynaSand. Select only one coagulant: simultaneous positive alum and ferric doses are unsupported. Percentage diagnostics at zero inlet load are unavailable."
    accepted = spec_review.accept(spec, "User-authorized review implementation and DynaSand distribution; inherited reviewed coefficients unchanged", confirm_all=True)
    assert accepted["accepted"], accepted
    (BUNDLE / "unit_spec.json").write_text(json.dumps(spec, indent=2), encoding="utf-8")
    emitted = unit_emitter.emit_unit(spec, BUNDLE, allow_bulk=True, group_info={"name": "DynaSand", "default_unit": NAME})
    assert emitted["emitted"], emitted
    shutil.copy2(original / (NAME + ".emf"), BUNDLE / (NAME + ".emf"))
    WORK.mkdir(parents=True, exist_ok=True)
    shutil.copy2(BUNDLE / "unit_spec.json", WORK / "unit_spec.json")
    for part in ("System files", "Model base"):
        shutil.copytree(original / "build" / part, WORK / "build" / part, dirs_exist_ok=True)
    units = WORK / "build" / "Process units" / "DynaSand"
    units.mkdir(parents=True, exist_ok=True)
    for path in BUNDLE.glob("*.xlsx"):
        shutil.copy2(path, units / path.name)
    install = resolve_install_dir(required=True)
    shutil.copy2(install / "Process code/Process units/20 Flow elements/Influent/State influent.xlsx", units / "State influent.xlsx")
    plant = plant_emitter.emit_test_plant(NAME, WORK / "build", unit_label="Filter", instance_name="dynasand_release", unit_class_path=emitted["workbook"])
    assert plant["emitted"], plant
    print(json.dumps({"prepared": True, "bundle": str(BUNDLE), "plant": plant}, default=str))


def build():
    import smt_runner, slc_runner
    artifacts = WORK / "artifacts"
    artifacts.mkdir(exist_ok=True)
    smt = smt_runner.run_smt(WORK / "build/Plant instances/dynasand_release.xlsx", artifacts / "model.xml", cwd=WORK / "build", timeout=180)
    (WORK / "smt.json").write_text(json.dumps(smt, indent=2, default=str), encoding="utf-8")
    assert smt["ok"], smt
    slc = slc_runner.run_slcompiler(artifacts / "model.xml", artifacts / "model.dll", artifacts / "src", cwd=artifacts, timeout=300)
    (WORK / "slc.json").write_text(json.dumps(slc, indent=2, default=str), encoding="utf-8")
    assert slc["ok"], slc
    print(json.dumps({"compiled": True}))


def validate():
    import tracer_test
    import dynamita.scheduler as ds
    artifacts = WORK / "artifacts"
    os.chdir(WORK)
    ports = ("Inflpipe", "Filtereff", "Filterwash")
    variables = ["Sumo__Time"] + [f"Sumo__Plant__{p}__{v}" for p in ports for v in ("Q", "XTSS")]
    results = {}
    try:
        for label, flow in (("positive_flow", 3000), ("zero_flow", 0)):
            commands = [f"set Sumo__Plant__Influent__param__Q {flow}", "set Sumo__StopTime 864000", "set Sumo__DataComm 86400", "mode dynamic", "start"]
            result = tracer_test.run_model(artifacts / "model.dll", variables, commands, timeout_s=90)
            result.pop("all_rows", None)
            assert result["ok"], result
            row = result["last"]
            residual = sum(s * row[f"Sumo__Plant__{p}__Q"] * row[f"Sumo__Plant__{p}__XTSS"] for s, p in zip((1, -1, -1), ports))
            assert abs(residual) < 1e-6, residual
            if flow:
                assert row["Sumo__Plant__Filtereff__XTSS"] < row["Sumo__Plant__Inflpipe__XTSS"]
            result["tss_load_residual_g_d"] = residual
            results[label] = result
    finally:
        ds.sumo.cleanup()
    (WORK / "native_validation.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    release = build_provenance.attest_release(BUNDLE, artifacts / "model.xml", artifacts / "model.dll", "dynasand-1.0.0-20260908", BUNDLES / "dynasand_release.json")
    release["validation"] = {"native_tests": list(results), "passed": True, "record_sha256": build_provenance.sha(WORK / "native_validation.json")}
    (BUNDLES / "dynasand_release.json").write_text(json.dumps(release, indent=2), encoding="utf-8")
    print(json.dumps({"validated": True, "release": release["release_id"]}))


if __name__ == "__main__":
    {"prepare": prepare, "build": build, "validate": validate}[sys.argv[1]]()
