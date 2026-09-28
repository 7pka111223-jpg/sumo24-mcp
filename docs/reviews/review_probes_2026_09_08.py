"""Isolated review probes; no native scheduler, SUMO GUI or installed files touched.

Run from MCP: python -X utf8 docs/reviews/review_probes_2026_09_08.py
These record existing defects, rather than asserting they are desired behavior.
Server functions are compiled from their actual AST to avoid import-time DLL loading.
"""
from __future__ import annotations

import ast
import asyncio
import copy
import json
import os
import pathlib
import sys
import tempfile
import threading
import time
import types

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "PY"))


def extract(filename, names, namespace):
    tree = ast.parse((ROOT / filename).read_text(encoding="utf-8-sig"))
    selected = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
            node.decorator_list = []
            selected.append(node)
    assert len(selected) == len(names)
    exec(compile(ast.Module(body=selected, type_ignores=[]), filename, "exec"), namespace)


class TextContent:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def main():
    results = {}
    ns = {"types": types.SimpleNamespace(TextContent=TextContent), "json": json,
          "CONFIG": {"law48_limits": {"TSS": 50, "BOD5": 60, "COD": 80}},
          "_job_lock": threading.Lock(), "_active_jobs": {}}
    extract("PY/server.py", {"_summarise", "_check_compliance", "call_tool"}, ns)
    for label, args in [("empty_compliance", {}), ("unknown_job_compliance", {"job_id": 999}),
                        ("partial_compliance", {"TSS_mgL": 1})]:
        results[label] = json.loads(asyncio.run(ns["call_tool"]("check_compliance", args))[0].text)
    results["time_summary"] = ns["_summarise"]([{"Sumo__Time": 86400000}])
    import academic_bundle
    import sumo_native
    results["missing_effluent_becomes_zero"] = academic_bundle._derive_effluent({})
    results["nonexistent_baseline_target"] = sumo_native.topology_match_report(
        {"units": [{"id": "u1", "type": "influent"}]},
        {"unit_ids": ["Influent1"]}, user_mapping={"u1": "DOES_NOT_EXIST"})

    shim = {"_lock": threading.Lock(), "_command_queue": [], "_param_overrides": {},
            "_active_project": None, "Path": pathlib.Path,
            "_ss_lookup": lambda v: "disk value"}
    extract("PY/dynamita_compat.py", {"_set", "_get", "_executeCommand", "set_active_project"}, shim)
    backend = types.SimpleNamespace(jobData={})
    shim["set_active_project"]("project_A.sumo")
    returned = shim["_set"](backend, "Sumo__Plant__Tank__param__V", 123)
    shim["set_active_project"]("project_B.sumo")
    results["shim"] = {"set_without_job_returns": returned,
                       "value_after_project_switch": shim["_get"](backend, "Sumo__Plant__Tank__param__V"),
                       "queued": shim["_command_queue"]}

    import spec_review
    spec = json.loads((ROOT / "custom_units/HH_DynaSand_v1/unit_spec.json").read_text(encoding="utf-8"))
    changed = copy.deepcopy(spec)
    for block in changed["code_blocks"]:
        for row in block["lines"]:
            if row["symbol"] == "eff..L.xSV":
                row["expression"] = "inp..L.xSV"
    results["acceptance_after_equation_change"] = {
        "original": spec_review.may_emit(spec, allow_bulk=True)["may_emit"],
        "changed": spec_review.may_emit(changed, allow_bulk=True)["may_emit"]}

    scratch = ROOT / ".scratch"
    scratch.mkdir(exist_ok=True)
    # All deletion probes target only a newly created, checked temporary directory.
    with tempfile.TemporaryDirectory(prefix="review-20260908-", dir=scratch) as tmp:
        td = pathlib.Path(tmp).resolve()
        assert td.is_relative_to(scratch.resolve())
        from pipeline import snapshot
        project = td / "project"
        (project / "snapshots").mkdir(parents=True)
        valuable = project / "user_work.txt"
        valuable.write_text("existing work", encoding="utf-8")
        (project / "snapshots/broken.tar").write_bytes(b"not an archive")
        try:
            snapshot.revert(project, "broken")
        except Exception as exc:
            results["corrupt_snapshot_revert"] = {
                "error": type(exc).__name__, "existing_file_survives": valuable.exists()}

        import tracer_test
        model = td / "fake.dll"
        model.write_bytes(b"test placeholder; never loaded")
        verification = {"_pipe_check": lambda: None, "Path": pathlib.Path, "os": os,
                        "_read_dll_symbols": lambda p: set()}
        state = {"plant_name": "missing_schematic", "stages": [{} for _ in range(9)]}
        verification["_pipe_m"] = types.SimpleNamespace(
            load=lambda p: state,
            set_stage=lambda m, i, **kw: m["stages"][i].update(kw),
            record=lambda *a: None, save=lambda *a: None)
        extract("PY/server.py", {"_exp_stage8_verify", "_exp_verify_dll_matches_schematic"}, verification)
        results["stage8_without_schematic"] = verification["_exp_stage8_verify"](
            {"project_dir": str(td), "dll_path": str(model)})
        old_message = lambda *a: None
        old_data = lambda *a: None
        fake = types.SimpleNamespace(persistent="persistent", message_callback=old_message,
                                     datacomm_callback=old_data, setLogDetails=lambda n: None,
                                     finish=lambda jid: None)

        def schedule(*args, **kwargs):
            fake.datacomm_callback(777, {"Sumo__Time": 1, "foreign_job_data": 42})
            fake.message_callback(777, "530004 simulation finished")
            return 42

        fake.schedule = schedule
        package = types.ModuleType("dynamita")
        package.__path__ = []
        scheduler = types.ModuleType("dynamita.scheduler")
        scheduler.sumo = fake
        package.scheduler = scheduler
        saved = {key: sys.modules.get(key) for key in ("dynamita", "dynamita.scheduler")}
        old_time = tracer_test.time
        try:
            sys.modules.update({"dynamita": package, "dynamita.scheduler": scheduler})
            tracer_test.time = types.SimpleNamespace(time=time.time, sleep=lambda n: None)
            r = tracer_test.run_model(model, ["Sumo__Time"], [], timeout_s=1)
            results["tracer_foreign_job"] = {"ok": r["ok"], "job_id": r["job_id"],
                                             "last": r.get("last"),
                                             "callbacks_restored": fake.message_callback is old_message
                                             and fake.datacomm_callback is old_data}
        finally:
            tracer_test.time = old_time
            for key, val in saved.items():
                if val is None:
                    sys.modules.pop(key, None)
                else:
                    sys.modules[key] = val

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
