"""
smoke_test_dd.py — Group EE end-to-end smoke test.

Old version: round-tripped a custom zip through custom code and reported PASS.
That was not a useful test because it never asked SUMO to open the file.

New version: tests sumo_pack output directly and either loads it in SUMO
(if available on this machine) or skips that step — never reports PASS
for a step it could not actually verify.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import sumo_pack as spk


# ---------- canonical test schematic (7-unit Mermaid Classic AS) ----------

SCHEMATIC = {
    "schema_version": "1.0",
    "meta": {
        "plant_name": "Classic AS Test",
        "design_flow_m3d": 10000,
        "temperature_C": 20,
    },
    "units": [
        {
            "id": "U1",
            "type": "influent",
            "name": "Raw Wastewater",
            "parameters": [
                {
                    "key": "Q",
                    "value": 10000,
                    "sumo_variable": "Sumo__Plant__Influent__param__Q",
                    "description": "Design flow",
                }
            ],
        },
        {
            "id": "U2",
            "type": "aerobic_zone",
            "name": "Aeration Tank",
            "parameters": [
                {
                    "key": "V",
                    "value": 3000,
                    "sumo_variable": "Sumo__Plant__Aerobic__param__V",
                    "description": "Volume m3",
                }
            ],
        },
        {"id": "U3", "type": "secondary_clarifier", "name": "Secondary Clarifier", "parameters": []},
        {"id": "U4", "type": "effluent",       "name": "Effluent",       "parameters": []},
        {"id": "U5", "type": "sludge_splitter","name": "Sludge Splitter", "parameters": []},
        {"id": "U6", "type": "ras_flow",       "name": "RAS",            "parameters": []},
        {"id": "U7", "type": "was_flow",       "name": "WAS Outlet",     "parameters": []},
    ],
    "streams": [
        {"id": "S1", "type": "process_flow", "from": "U1", "to": "U2"},
        {"id": "S2", "type": "process_flow", "from": "U2", "to": "U3"},
        {"id": "S3", "type": "process_flow", "from": "U3", "to": "U4"},
        {"id": "S4", "type": "process_flow", "from": "U3", "to": "U5"},
        {"id": "S5", "type": "ras",          "from": "U5", "to": "U6"},
        {"id": "S6", "type": "ras",          "from": "U6", "to": "U2"},
        {"id": "S7", "type": "was",          "from": "U5", "to": "U7"},
    ],
}


# ---------- individual tests ------------------------------------------------

def test_pack_generates_required_files(tmp: Path):
    out = spk.build_pack(SCHEMATIC, tmp / "test.sumo-pack", overwrite=True)
    assert out["ok"], f"build_pack failed: {out}"
    for fname in (
        "plant.sumoslang",
        "apply_parameters.scs",
        "BUILD_INSTRUCTIONS.md",
        "schematic.json",
    ):
        assert (tmp / "test.sumo-pack" / fname).is_file(), f"missing {fname}"
    print(f"  [ok] pack written with {len(out['files'])} files: {out['files']}")


def test_sumoslang_lints_clean(tmp: Path):
    slang = (tmp / "test.sumo-pack" / "plant.sumoslang").read_text()
    lint = spk.validate_sumoslang(slang)
    assert lint["ok"], f"lint failed: {lint}"
    print(f"  [ok] SumoSlang lints clean ({len(lint['warnings'])} warning(s))")


def test_schematic_json_round_trips(tmp: Path):
    stored = json.loads((tmp / "test.sumo-pack" / "schematic.json").read_text())
    assert stored["units"] == SCHEMATIC["units"], "schematic.json round-trip mismatch"
    print("  [ok] schematic.json round-trips correctly")


def test_overwrite_flag(tmp: Path):
    """build_pack must raise FileExistsError when overwrite=False."""
    try:
        spk.build_pack(SCHEMATIC, tmp / "test.sumo-pack", overwrite=False)
        raise AssertionError("Expected FileExistsError was not raised")
    except FileExistsError:
        print("  [ok] overwrite=False correctly raises FileExistsError")


def test_baseline_apply_refuses_without_baseline(tmp: Path):
    """apply_to_baseline must refuse with a clear error when the baseline is missing."""
    try:
        spk.apply_to_baseline(
            SCHEMATIC,
            baseline_sumo=tmp / "does-not-exist.sumo",
            baseline_dll=tmp / "does-not-exist.dll",
            output_sumo=tmp / "out.sumo",
        )
        raise AssertionError("Expected FileNotFoundError was not raised")
    except FileNotFoundError:
        print("  [ok] apply_to_baseline correctly refuses missing baseline")


def test_empty_schematic_raises(tmp: Path):
    """build_pack must raise ValueError for a schematic with no units."""
    try:
        spk.build_pack(
            {"units": [], "streams": []},
            tmp / "empty.sumo-pack",
            overwrite=True,
        )
        raise AssertionError("Expected ValueError was not raised")
    except ValueError:
        print("  [ok] empty schematic correctly raises ValueError")


def test_sumo_loads_pack_if_available(tmp: Path):
    """
    The honest integration test. Only runs if SUMO24 + DTT are importable
    on this machine. Marked SKIPPED otherwise — never reports PASS for an
    absent SUMO instance.
    """
    try:
        import dynamita.scheduler  # type: ignore  # noqa: F401
    except ImportError:
        print(
            "  [skip] SUMO24 / DTT not importable on this machine — "
            "manual verification required. Follow BUILD_INSTRUCTIONS.md "
            "to confirm the pack is accepted by SUMO24 GUI."
        )
        return

    # If DTT is available: load, compile, and verify.
    # (Placeholder — implement once DTT capability is confirmed per §9 of Fix Plan.)
    print(
        "  [todo] DTT importable — implement load/compile test against "
        "generated pack once DTT project-creation API is confirmed."
    )


# ---------- runner ----------------------------------------------------------

def main():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        print("Group EE smoke test (sumo_pack — replaces old Group DD zip test)")
        test_pack_generates_required_files(tmp)
        test_sumoslang_lints_clean(tmp)
        test_schematic_json_round_trips(tmp)
        test_overwrite_flag(tmp)
        test_baseline_apply_refuses_without_baseline(tmp)
        test_empty_schematic_raises(tmp)
        test_sumo_loads_pack_if_available(tmp)
    print("All tests done.")


if __name__ == "__main__":
    main()
