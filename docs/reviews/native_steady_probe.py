from pathlib import Path
import json
import os
import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "PY"), str(ROOT)]
import tracer_test
import dynamita.scheduler as ds
work = ROOT / "docs/reviews/implementation-2026-09-08/runtime"
if "separator" in sys.argv:
    work = ROOT / "docs/reviews/implementation-2026-09-08/dynasand_build/artifacts"
os.chdir(work)
try:
    if "separator" in sys.argv:
        result = tracer_test.run_model(work / "model.dll", ["Sumo__Time", "Sumo__Plant__Filtereff__XTSS"],
            [f'save "{work / "state.xml"}"', "set Sumo__StopTime 86400000", "set Sumo__DataComm 360000", "mode steady", "start"], timeout_s=15)
        result.pop("all_rows", None)
        print(json.dumps(result, indent=2))
        raise SystemExit(0 if result["ok"] else 1)
    result = tracer_test.run_model(work / "sumoproject.dll", ["Sumo__Time", "Sumo__Plant__Effluent1__XTSS"],
        [f'load "{work / "state.xml"}"', "set Sumo__StopTime 86400000", "set Sumo__DataComm 360000", "mode steady", "start"], timeout_s=15)
    result.pop("all_rows", None)
    (work.parent / "steady-native-diagnostic.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
finally:
    ds.sumo.cleanup()
