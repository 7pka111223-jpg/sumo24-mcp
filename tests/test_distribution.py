import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "PY"))
from dynasand_validation import validate_parameters
import build_provenance
import native_launch


class DistributionTests(unittest.TestCase):
    def test_saved_edits_do_not_initialize_native_runtime(self):
        sys.path.insert(0, str(ROOT))
        import dynamita.scheduler as scheduler
        import dynamita_compat
        scheduler_instance = scheduler._LazyScheduler()
        with patch.object(scheduler.SumoScheduler, "__init__", side_effect=AssertionError("native initialization")):
            scheduler_instance.set("saved_only_test", 12)
            self.assertEqual(scheduler_instance.get("saved_only_test"), 12)
        dynamita_compat.consume_commands(["set saved_only_test 12"])

    def test_compilers_share_exclusive_lock(self):
        from compiler_lock import acquire, serialized
        @serialized
        def run():
            self.fail("must not execute while another compiler owns native resources")
        with acquire():
            self.assertEqual(run()["stage"], "busy")

    def test_bundle_matches_validated_release_and_exact_palette_family(self):
        bundle = ROOT / "PY/bundled_units/HH_DynaSand_v1"
        self.assertTrue(build_provenance.verify_release(bundle, bundle.parent / "dynasand_release.json")["ok"])
        from openpyxl import load_workbook
        workbook = load_workbook(bundle / "DynaSand Group Info.xlsx", read_only=True)
        self.assertEqual(workbook["Unit"]["C2"].value, "DynaSand")
        workbook.close()
        spec = json.loads((bundle / "unit_spec.json").read_text())
        import spec_review
        self.assertTrue(spec_review.may_emit(spec, allow_bulk=True)["may_emit"])

    def test_doses_are_finite_exclusive_and_scoped_per_unit(self):
        validate_parameters({"Sumo__Plant__A__param__Dose__alum": 10, "Sumo__Plant__B__param__Dose__fe": 10})
        with self.assertRaisesRegex(ValueError, "simultaneous"):
            validate_parameters({"Sumo__Plant__A__param__Dose__alum": 10, "Sumo__Plant__A__param__Dose__fe": 10})
        with self.assertRaises(ValueError):
            validate_parameters({"Dose,alum": float("nan")})

    @unittest.skipUnless(sys.platform == "win32", "Windows client job policy")
    def test_incompatible_client_policy_fails_before_native_launch(self):
        import win32job
        with patch.object(win32job, "IsProcessInJob", return_value=True), patch.object(win32job, "QueryInformationJobObject", return_value={"BasicLimitInformation": {"LimitFlags": 0}}):
            with self.assertRaisesRegex(RuntimeError, "Windows Job Object"):
                native_launch.check_native_launch()
