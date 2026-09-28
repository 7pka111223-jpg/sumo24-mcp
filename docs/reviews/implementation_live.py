"""Live public MCP regression test after the architecture review fixes."""
import asyncio
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/reviews/implementation-2026-09-08"


async def main():
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    if "compatible-job" in sys.argv:
        # Explicit integration-test client policy. SUMO's native scheduler starts
        # workers with CREATE_BREAKAWAY_FROM_JOB; SDK's default job forbids it.
        import mcp.os.win32.utilities as winclient
        import win32job
        original = winclient._create_job_object
        def compatible_job():
            job = original()
            info = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
            info["BasicLimitInformation"]["LimitFlags"] |= win32job.JOB_OBJECT_LIMIT_BREAKAWAY_OK
            win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, info)
            return job
        winclient._create_job_object = compatible_job
    work = OUT / "runtime"
    work.mkdir(parents=True, exist_ok=True)
    for name in ("sumoproject.dll", "state.xml"):
        if not (work / name).exists():
            shutil.copy2(ROOT / name, work / name)
    env = dict(os.environ, SUMO_INSTALL_DIR=r"D:\SUMO24", PYTHONPATH=str(ROOT), SUMO_DLL=str(work / "sumoproject.dll"),
               SUMO_STATE=str(work / "state.xml"), SUMO_OUTPUT=str(work / "outputs"), PYTHONUTF8="1")
    if "separator" in sys.argv:
        work = OUT / "dynasand_build/artifacts"
        env.update(SUMO_DLL=str(work / "model.dll"), SUMO_STATE=str(work / "state.xml"), SUMO_EFFLUENT_UNIT="Filtereff")
    server_path = ROOT / "PY/server.py"
    if "installed" in sys.argv:
        import sumo24_mcp
        server_path = Path(sumo24_mcp.__file__).with_name("server.py")
        env.pop("PYTHONPATH", None)
    params = StdioServerParameters(command=sys.executable, args=[str(server_path)], env=env, cwd=str(work))
    with (OUT / "mcp-stderr.txt").open("w", encoding="utf-8") as errlog:
        async with stdio_client(params, errlog=errlog) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert len(tools.tools) == 235, len(tools.tools)
                async def call(name, args, label=None):
                    result = await asyncio.wait_for(session.call_tool(name, args), 150)
                    suffix = "-separator" if "separator" in sys.argv else "-blocked-client" if "compatible-job" not in sys.argv and "gui" not in sys.argv else ""
                    (OUT / ((label or name) + suffix + ".json")).write_text(json.dumps(result.model_dump(), indent=2), encoding="utf-8")
                    print(json.dumps({"tool": name, "isError": result.isError}), flush=True)
                    texts = [c.text for c in result.content if c.type == "text"]
                    return result, json.loads(texts[0]) if texts and texts[0].startswith("{") else texts
                if "gui" in sys.argv:
                    for name, args in (("launch_sumo_gui", {}), ("gui_get_window_rect", {}), ("gui_screenshot", {"output_dir": str(OUT)})):
                        result, value = await call(name, args)
                        assert not result.isError, value
                    print("GUI held for review; create release-gui marker to exit", flush=True)
                    for _ in range(1200):
                        if (OUT / "release-gui").exists():
                            break
                        await asyncio.sleep(1)
                    return
                result, empty = await call("check_compliance", {})
                assert "COMPLIANT" not in json.dumps(empty).replace("INSUFFICIENT_DATA", "")
                result, run = await call("run_dynamic_simulation", {"duration_days": 0.01, "datacomm_hours": 0.01})
                if "compatible-job" not in sys.argv:
                    assert result.isError and "Windows Job Object" in json.dumps(run), run
                    assert len((await session.list_tools()).tools) == 235
                    print('{"blocked_client_reported_without_crash": true}')
                    return
                assert not result.isError, run
                for _ in range(100):
                    result, status = await call("get_job_status", {"job_id": run["job_id"]})
                    if status["status"] not in ("running", "queued", "scheduled"):
                        break
                    await asyncio.sleep(0.2)
                assert status["status"] == "finished", status
                assert abs(status["summary"]["time_days"] - 0.01) < 1e-8, status
                assert "COD_mgL" in status["summary"] and "BOD5_mgL" in status["summary"], status
                if "separator" in sys.argv:
                    result, steady = await call("run_steady_state", {})
                    assert not result.isError and steady["status"] == "finished", steady
                print(json.dumps({"passed": True, "tools": len(tools.tools), "dynamic": status["summary"]}), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
