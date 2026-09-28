"""Portable regression tests for review failures; no native SUMO import required."""
import ast
import asyncio
import math
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import importlib.util
import json
import types
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

PY = Path(__file__).resolve().parents[1] / "PY"
sys.path.insert(0, str(PY))
from runtime_results import summarise, check_compliance, compliance_outcome, effluent_mapping, influent_commands, DAY
from sumo_runtime import Runtime, Operation, run_operation, get_runtime
from tool_registry import ToolRegistry


class FakeScheduler:
    persistent = "persistent"
    def __init__(self):
        self.next_id = 1
        self.finished = []
        self.early = False
        self.fail = False

    def schedule(self, model, commands, variables, jobData):
        if self.fail:
            raise RuntimeError("schedule failed")
        jid = self.next_id
        self.next_id += 1
        if self.early:
            self.datacomm_callback(777, {"foreign": 1})
            self.message_callback(777, "530004 finished")
            self.datacomm_callback(jid, {"own": 2})
            self.message_callback(jid, "530004 finished")
        return jid

    def isSimFinishedMsg(self, msg):
        return msg.startswith("530004")

    def finish(self, jid):
        self.finished.append(jid)


class RuntimeReviewTests(unittest.TestCase):
    def test_registry_preserves_schema_and_dispatches_registered_handlers(self):
        registry = ToolRegistry()
        tool = types.SimpleNamespace(name="example", inputSchema={"type": "object"})
        async def handler(name, arguments):
            return arguments
        self.assertEqual(registry.bind([tool], handler), [tool])
        self.assertEqual(asyncio.run(registry.dispatch("example", {"a": 1})), {"a": 1})
        with self.assertRaises(ValueError):
            registry.bind([tool, tool], handler)
        with self.assertRaises(ValueError):
            asyncio.run(registry.dispatch("unknown", {}))

    def load_compat(self):
        module = types.ModuleType("dynamita.scheduler")
        module.SumoScheduler = type("TestScheduler", (), {})
        package = types.ModuleType("dynamita")
        package.scheduler = module
        spec = importlib.util.spec_from_file_location("review_compat", PY / "dynamita_compat.py")
        compat = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"dynamita": package, "dynamita.scheduler": module}):
            spec.loader.exec_module(compat)
        return compat

    def test_project_switch_cannot_read_or_apply_previous_overrides(self):
        compat = self.load_compat()
        with tempfile.TemporaryDirectory() as folder:
            a, b = Path(folder) / "a" / "test.sumo", Path(folder) / "b" / "test.sumo"
            b.parent.mkdir()
            (b.parent / "state.xml").write_text('<state><real name="x" value="9"/></state>')
            compat.set_active_project(a)
            self.assertEqual(compat._set(None, "x", 2)["status"], "queued")
            compat.set_active_project(b)
            self.assertEqual(compat.get_queue(), [])
            self.assertEqual(compat._get(None, "x"), 9)
            self.assertEqual(compat._getVariableNames(None), ["x"])

    def test_queued_edits_never_choose_a_live_job_and_capture_provenance(self):
        compat = self.load_compat()
        class Scheduler:
            jobData = {1: {}, 999: {}}
            def sendCommand(self, *args):
                raise AssertionError("Queued edits cannot choose a live job")
        compat.begin_activity()
        self.assertEqual(compat._set(Scheduler(), "x", 3)["status"], "queued")
        self.assertEqual(compat._get(None, "x"), 3)
        self.assertEqual(compat.activity()["read_sources"], ["pending_override"])
        compat.consume_commands(["set x 3"])
        self.assertEqual(compat.get_queue(), [])
        self.assertEqual(compat.get_overrides(), {})

    def test_empty_partial_nan_and_soluble_cod_cannot_pass(self):
        limits = {"TSS": 30, "BOD5": 30, "COD": 80}
        for sample in ({}, {"TSS_mgL": 1}, {"TSS_mgL": 1, "BOD5_mgL": 1, "sCOD_mgL": 1},
                       {"TSS_mgL": math.nan, "BOD5_mgL": 1, "COD_mgL": 1}):
            self.assertEqual(compliance_outcome(check_compliance(sample, limits)), "INSUFFICIENT_DATA")
        self.assertEqual(compliance_outcome(check_compliance(
            {"TSS_mgL": 1, "BOD5_mgL": 1, "COD_mgL": 1}, limits)), "COMPLIANT")

    def test_model_mapping_time_and_metric_identity(self):
        result = summarise([{"Sumo__Time": DAY, "Sumo__Plant__Effluent1__XTSS": 3,
                             "Sumo__Plant__Effluent1__TBOD_5": 2, "Sumo__Plant__Effluent1__TCOD": 20}])
        self.assertEqual(result["time_days"], 1)
        self.assertEqual(result["COD_mgL"], 20)
        self.assertEqual(result["BOD5_mgL"], 2)
        self.assertEqual(result["observations"]["COD_mgL"]["source"], "native_datacomm")
        with self.assertRaises(ValueError):
            effluent_mapping(["Sumo__Plant__Effluent1__Q", "Sumo__Plant__Effluent2__Q"])

    def test_influent_resolves_actual_model_and_rejects_unsupported_cod(self):
        with tempfile.TemporaryDirectory() as folder:
            state = Path(folder) / "state.xml"
            state.write_text('<state><real name="Sumo__Plant__Influent1__param__Q" value="2"/></state>')
            self.assertEqual(influent_commands({"influent_flow_m3d": 4}, state),
                             ["set Sumo__Plant__Influent1__param__Q 4"])
            with self.assertRaises(ValueError):
                influent_commands({"influent_cod_mgL": 30}, state)

    def test_real_tracer_preserves_running_normal_job(self):
        import tracer_test
        scheduler = FakeScheduler()
        runtime = get_runtime(scheduler)
        normal = runtime.schedule("x", [], [])
        module = types.ModuleType("dynamita.scheduler")
        module.sumo = scheduler
        package = types.ModuleType("dynamita")
        package.scheduler = module
        scheduler.early = True
        with tempfile.TemporaryDirectory() as folder:
            dll = Path(folder) / "model.dll"
            dll.write_bytes(b"test fixture")
            with patch.dict(sys.modules, {"dynamita": package, "dynamita.scheduler": module}):
                result = tracer_test.run_model(dll, [], [], timeout_s=0)
        self.assertTrue(result["ok"])
        self.assertEqual(result["last"], {"own": 2})
        scheduler.datacomm_callback(normal, {"normal": 3})
        self.assertEqual(runtime.jobs[normal]["rows"], [{"normal": 3}])
        self.assertEqual(runtime.jobs[normal]["status"], "running")

    def test_overlapping_callbacks_are_isolated_and_stable(self):
        scheduler = FakeScheduler()
        runtime = Runtime(scheduler)
        owner = scheduler.message_callback
        first = runtime.schedule("x", [], [])
        second = runtime.schedule("x", [], [])
        scheduler.datacomm_callback(first, {"one": 1})
        scheduler.datacomm_callback(second, {"two": 2})
        scheduler.message_callback(first, "530004 finished")
        self.assertEqual(runtime.jobs[first]["rows"], [{"one": 1}])
        self.assertEqual(runtime.jobs[second]["status"], "running")
        self.assertEqual(scheduler.message_callback, owner)
        runtime.cancel(second)
        self.assertEqual(scheduler.finished, [first, second])

    def test_schedule_early_callbacks_ignore_foreign_job(self):
        scheduler = FakeScheduler()
        scheduler.early = True
        runtime = Runtime(scheduler)
        jid = runtime.schedule("x", [], [])
        self.assertEqual(runtime.jobs[jid]["rows"], [{"own": 2}])
        self.assertNotIn(777, runtime.jobs)
        self.assertEqual(runtime.jobs[jid]["status"], "finished")

    def test_schedule_exception_releases_and_timeout_stops_owned_job(self):
        scheduler = FakeScheduler()
        runtime = Runtime(scheduler)
        scheduler.fail = True
        with self.assertRaises(RuntimeError):
            runtime.schedule("x", [], [])
        scheduler.fail = False
        first = runtime.schedule("x", [], [])
        second = runtime.schedule("x", [], [])
        self.assertEqual(runtime.wait(first, 0)["status"], "timed_out")
        self.assertEqual(runtime.jobs[second]["status"], "running")
        self.assertEqual(scheduler.finished, [first])

    def test_operation_cancel_only_its_job(self):
        scheduler = FakeScheduler()
        runtime = Runtime(scheduler)
        other = runtime.schedule("x", [], [])
        operation = Operation()
        own = run_operation(operation, lambda: runtime.schedule("x", [], []))
        operation.cancel()
        self.assertEqual(runtime.jobs[own]["status"], "cancelled")
        self.assertEqual(runtime.jobs[other]["status"], "running")

    def test_rows_are_bounded_and_labeled(self):
        scheduler = FakeScheduler()
        runtime = Runtime(scheduler, max_rows=2)
        jid = runtime.schedule("x", [], [])
        for i in range(3):
            scheduler.datacomm_callback(jid, {"i": i})
        self.assertEqual(len(runtime.jobs[jid]["rows"]), 2)
        self.assertTrue(runtime.jobs[jid]["rows_truncated"])

    def test_real_build_command_function_uses_milliseconds(self):
        source = ast.parse((PY / "server.py").read_text(encoding="utf-8"))
        fn = next(n for n in source.body if isinstance(n, ast.FunctionDef) and n.name == "_build_commands")
        scope = {"math": math, "DAY": DAY, "HOUR": 3600000, "CONFIG": {"state_xml": "state.xml"}, "SCENARIOS": {}}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), "server.py", "exec"), scope)
        commands = scope["_build_commands"](stop_days=1)
        self.assertIn("set Sumo__StopTime 86400000", commands)
        with self.assertRaises(ValueError):
            scope["_build_commands"](stop_days=math.inf)

    def test_public_compliance_rejects_unknown_and_incomplete_jobs(self):
        source = ast.parse((PY / "server.py").read_text(encoding="utf-8"))
        fn = next(n for n in source.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "_call_tool_impl")
        scope = {"types": types.SimpleNamespace(TextContent=lambda **kw: types.SimpleNamespace(**kw)),
                 "json": json, "_job_lock": threading.Lock(), "_active_jobs": {2: {"status": "running", "rows": []}},
                 "_summarise": summarise, "_check_compliance": lambda data: check_compliance(data, {"TSS": 30, "BOD5": 30, "COD": 80}),
                 "compliance_outcome": compliance_outcome}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), "server.py", "exec"), scope)
        for args in ({}, {"job_id": 999}, {"job_id": 2}, {"TSS_mgL": 1}):
            result = asyncio.run(scope["_call_tool_impl"]("check_compliance", args))
            self.assertEqual(json.loads(result[0].text)["overall"], "INSUFFICIENT_DATA")

    def test_transport_is_responsive_during_blocking_work_and_marks_errors(self):
        import time
        source = ast.parse((PY / "server.py").read_text(encoding="utf-8"))
        fn = next(n for n in source.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "call_tool")
        fn.decorator_list = []
        def block(text):
            return types.SimpleNamespace(text=text)
        async def invoke(name, args):
            if name == "slow":
                time.sleep(0.3)
            return [block('{"error": "test failure"}' if name == "bad" else '{}')]
        with ThreadPoolExecutor(max_workers=1) as executor:
            scope = {"asyncio": asyncio, "json": json, "Operation": Operation, "run_operation": run_operation,
                     "_invoke_with_provenance": invoke, "_tool_worker": executor,
                     "types": types.SimpleNamespace(TextContent=lambda **kw: types.SimpleNamespace(**kw),
                         CallToolResult=lambda **kw: types.SimpleNamespace(**kw))}
            exec(compile(ast.Module(body=[fn], type_ignores=[]), "server.py", "exec"), scope)
            async def scenario():
                slow = asyncio.create_task(scope["call_tool"]("slow", {}))
                await asyncio.sleep(0.05)
                start = time.monotonic()
                await scope["call_tool"]("get_job_status", {})
                self.assertLess(time.monotonic() - start, 0.15)
                await slow
                self.assertTrue((await scope["call_tool"]("bad", {})).isError)
            asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
