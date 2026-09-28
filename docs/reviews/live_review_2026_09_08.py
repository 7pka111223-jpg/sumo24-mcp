"""Live review runner. Each command records evidence; production sources are not edited.

prepare/build/mcp/simulate/install/uninstall are explicit operations. Install/uninstall
touch only the separately named HH_ReviewProbe_v1 in the HH Review Audit family.
"""
from __future__ import annotations
import argparse
import asyncio
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs/reviews/live-2026-09-08"
SLUG = EVIDENCE / "HH_ReviewProbe_v1"
NAME = "HH_ReviewProbe_v1"
sys.path[:0] = [str(ROOT / "PY"), str(ROOT)]


def record(name, value):
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / (name + ".json")).write_text(json.dumps(value, indent=2, default=str), encoding="utf-8")
    summary = {k: v for k, v in value.items() if k in ("ok", "reason", "stage", "rows", "worst_rel", "n_imbalances", "installed", "uninstalled", "isError", "elapsed_s")}
    print(json.dumps({"evidence": name, "summary": summary}, default=str), flush=True)
    return value


def prepare():
    import spec_review, unit_emitter, plant_emitter
    original = ROOT / "custom_units/HH_DynaSand_v1"
    if SLUG.exists():
        raise RuntimeError("Review fixture exists; refusing to overwrite it")
    SLUG.mkdir(parents=True)
    spec = json.loads((original / "unit_spec.json").read_text(encoding="utf-8"))
    spec["identity"].update(name="Review audit separator", qualified_name=NAME)
    spec["description"] = "Temporary live-review fixture, cloned from DynaSand. Remove after review."
    spec["provenance"].pop("accepted", None)
    accepted = spec_review.accept(spec, "Live review fixture: user-authorized installation test; inherited accepted parameter values", confirm_all=True)
    assert accepted["accepted"], accepted
    (SLUG / "unit_spec.json").write_text(json.dumps(spec, indent=2), encoding="utf-8")
    emitted = unit_emitter.emit_unit(spec, SLUG, allow_bulk=True,
                                    group_info={"name": "HH Review Audit", "default_unit": NAME})
    assert emitted["emitted"], emitted
    shutil.copy2(original / "HH_DynaSand_v1.emf", SLUG / (NAME + ".emf"))
    build = SLUG / "build"
    for sub in ("System files", "Model base"):
        shutil.copytree(original / "build" / sub, build / sub)
    unit_dir = build / "Process units" / "Review Audit"
    unit_dir.mkdir(parents=True)
    for path in SLUG.glob("*.xlsx"):
        shutil.copy2(path, unit_dir / path.name)
    plant = plant_emitter.emit_test_plant(NAME, build, unit_label="Probe",
                                          instance_name="hh_reviewprobe_v1", unit_class_path=emitted["workbook"])
    assert plant["emitted"], plant
    (SLUG / "artifacts").mkdir()
    work = EVIDENCE / "runtime"
    work.mkdir()
    for name in ("sumoproject.dll", "state.xml", "Verified BOD.sumo"):
        shutil.copy2(ROOT / name, work / name)
    record("prepare", {"unit": emitted, "plant": plant, "runtime_project": str(work)})


def build():
    import smt_runner, slc_runner
    art = SLUG / "artifacts"
    r = record("smt", smt_runner.run_smt(SLUG / "build/Plant instances/hh_reviewprobe_v1.xlsx",
              art / "review.xml", cwd=SLUG / "build", timeout=180))
    if not r["ok"]:
        return
    record("slcompiler", slc_runner.run_slcompiler(art / "review.xml", art / "review.dll",
                                                   art / "src", cwd=art, timeout=300))


def simulate():
    import tracer_test
    import dynamita.scheduler as ds
    os.chdir(EVIDENCE / "runtime")
    try:
        h = Path(r"C:\Users\DELL\AppData\Local\Temp\slc_rev\out")
        for label, stem in [("nonreactive", "final"), ("reactive", "r25_sorted")]:
            record("tracer_" + label, tracer_test.rung5a_conservative_tracer(
                h / (stem + ".dll"), h / (stem + ".xml"), horizon_days=20, timeout_s=90))
        record("degenerate_equivalence", tracer_test.rung5b_degenerate_equivalence(
            h / "r25_sorted.dll", h / "r25_sorted.xml", h / "final.dll", h / "final.xml",
            horizon_days=20, timeout_s=90))
        record("tracer_negative_wrong_port", tracer_test.rung5a_conservative_tracer(
            h / "final.dll", h / "final.xml", in_port="Inflpipe", out_port="Influentoutp", horizon_days=20, timeout_s=90))
        record("tracer_negative_nosort", tracer_test.rung5a_conservative_tracer(
            h / "r24_diffcalc.dll", h / "r24_diffcalc.xml", horizon_days=1, timeout_s=90))
        art = SLUG / "artifacts"
        if (art / "review.dll").exists():
            ports = ["Inflpipe", "Probeeff", "Probewash"]
            variables = ["Sumo__Time"] + [f"Sumo__Plant__{p}__{v}" for p in ports for v in ["Q", "XTSS", "XB"]]
            for label, q in [("positive_flow", 3000), ("zero_flow", 0)]:
                cmds = [f"set Sumo__Plant__Influent__param__Q {q}",
                        "set Sumo__Plant__Influent__param__XB 183",
                        "set Sumo__StopTime 864000", "set Sumo__DataComm 86400", "mode dynamic", "start"]
                r = tracer_test.run_model(art / "review.dll", variables, cmds, timeout_s=90)
                r.pop("all_rows", None)
                if r.get("last"):
                    last = r["last"]
                    r["flow_residual"] = last["Sumo__Plant__Inflpipe__Q"] - last["Sumo__Plant__Probeeff__Q"] - last["Sumo__Plant__Probewash__Q"]
                    r["tss_mass_residual"] = sum(sign * last[f"Sumo__Plant__{p}__Q"] * last[f"Sumo__Plant__{p}__XTSS"] for p, sign in zip(ports, [1, -1, -1]))
                record("separator_" + label, r)
    finally:
        ds.sumo.cleanup()


async def mcp_check(gui=False):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    work = EVIDENCE / "runtime"
    env = dict(os.environ, PYTHONPATH=str(ROOT), SUMO_DLL=str(work / "sumoproject.dll"),
               SUMO_STATE=str(work / "state.xml"), SUMO_OUTPUT=str(work / "outputs"), PYTHONUTF8="1")
    parameters = StdioServerParameters(command=sys.executable, args=[str(ROOT / "PY/server.py")],
                                       env=env, cwd=str(work))
    with (EVIDENCE / "mcp-server-stderr.txt").open("w", encoding="utf-8") as errlog:
        async with stdio_client(parameters, errlog=errlog) as streams:
            async with ClientSession(*streams) as session:
                init = await session.initialize()
                listed = await session.list_tools()
                record("mcp_initialize", {"server": init.serverInfo.model_dump(), "tools": len(listed.tools)})
                cases = [("check_compliance", {}), ("hh_check_environment", {}),
                                   ("run_dynamic_simulation", {"duration_days": 0.01, "datacomm_hours": 0.01}),
                                   ("run_steady_state", {})]
                if gui:
                    cases = [("launch_sumo_gui", {}), ("gui_get_window_rect", {}),
                             ("gui_screenshot", {"output_dir": str(EVIDENCE)})]
                for name, args in cases:
                    started = time.monotonic()
                    try:
                        result = await asyncio.wait_for(session.call_tool(name, args), timeout=145)
                        record("mcp_" + name, {"elapsed_s": time.monotonic()-started, **result.model_dump()})
                    except Exception as exc:
                        record("mcp_" + name, {"elapsed_s": time.monotonic()-started, "exception": repr(exc)})
                if gui:
                    print("GUI client kept alive for desktop review", flush=True)
                    for _ in range(1200):
                        if (EVIDENCE / "release-gui-client").exists():
                            break
                        await asyncio.sleep(1)


def baseline():
    import tracer_test
    import dynamita.scheduler as ds
    work = EVIDENCE / "runtime"
    os.chdir(work)
    try:
        variables = ["Sumo__Time"] + [f"Sumo__Plant__{u}__{v}" for u in ["Influent1", "Effluent1"] for v in ["Q", "XTSS", "TCOD", "TBOD_5", "SNHx"]]
        cmds = [f'load "{work / "state.xml"}"', "set Sumo__StopTime 864000",
                "set Sumo__DataComm 86400", "mode dynamic", "start"]
        r = tracer_test.run_model(work / "sumoproject.dll", variables, cmds, timeout_s=120)
        r.pop("all_rows", None)
        record("baseline_native_dynamic", r)
    finally:
        ds.sumo.cleanup()


def install(remove=False):
    import unit_installer
    if remove:
        record("uninstall", unit_installer.uninstall_process_unit(SLUG, opt_in=True))
        return
    dry = record("install_preflight", unit_installer.install_process_unit(
        SLUG, opt_in=True, unit_name=NAME, allow_bulk=True, category="99 HH Review Audit", dry_run=True))
    expected = Path(r"D:\SUMO24\Dir\My Process Code\Process Units\99 HH Review Audit\HH Review Audit").resolve()
    assert dry.get("dry_run") and Path(dry["destination"]).resolve() == expected, dry
    assert not any(Path(p).exists() for p in dry["would_write"]), "Refusing to overwrite existing installed files"
    record("install", unit_installer.install_process_unit(
        SLUG, opt_in=True, unit_name=NAME, allow_bulk=True, category="99 HH Review Audit"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=["prepare", "build", "simulate", "baseline", "mcp", "gui", "install", "uninstall"])
    op = parser.parse_args().operation
    if op == "mcp":
        asyncio.run(mcp_check())
    elif op == "gui":
        asyncio.run(mcp_check(gui=True))
    elif op == "uninstall":
        install(True)
    else:
        globals()[op]()
