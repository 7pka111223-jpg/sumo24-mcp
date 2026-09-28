"""Portable regression tests for artifact, restore, and reporting evidence."""
import io
import hashlib
import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "PY"))
from pipeline.snapshot import snapshot, revert
from pipeline.verification import verify_stage8
import spec_review
import sumo_native
import sumo_offline
import academic_bundle


class VerificationTests(unittest.TestCase):
    def test_spec_code_identity_ports_revoke_approval(self):
        path = Path(__file__).resolve().parents[1] / "custom_units/HH_DynaSand_v1/unit_spec.json"
        spec = json.loads(path.read_text(encoding="utf-8"))
        self.assertTrue(spec_review.accept(spec, "regression fixture", confirm_all=True)["accepted"])
        self.assertTrue(spec_review.may_emit(spec, allow_bulk=True)["may_emit"])
        for key in ("code", "identity", "ports"):
            changed = json.loads(json.dumps(spec))
            changed[key] = {"changed": True}
            self.assertFalse(spec_review.may_emit(changed, allow_bulk=True)["may_emit"])

    def test_restore_corruption_and_traversal_preserve_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "project.yaml").write_text("plant_name: test\n")
            (p / "work.txt").write_text("keep")
            (p / "snapshots").mkdir()
            bad = p / "snapshots/bad.tar"
            bad.write_bytes(b"broken")
            with self.assertRaises(tarfile.ReadError):
                revert(p, "bad")
            with tarfile.open(bad, "w") as archive:
                member = tarfile.TarInfo("../escaped.txt")
                member.size = 4
                archive.addfile(member, io.BytesIO(b"evil"))
            with self.assertRaises(ValueError):
                revert(p, "bad")
            self.assertEqual((p / "work.txt").read_text(), "keep")

    def test_restore_commit_failure_rolls_back_and_valid_restore_keeps_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "project.yaml").write_text("plant_name: test\n")
            (p / "work.txt").write_text("old")
            snapshot(p, "valid")
            (p / "work.txt").write_text("current")
            with patch.object(tarfile.TarFile, "extractall", side_effect=OSError("injected extraction failure")):
                with self.assertRaises(OSError):
                    revert(p, "valid")
            self.assertEqual((p / "work.txt").read_text(), "current")
            real_rename = Path.rename
            failed = False
            def fail_once(path, target):
                nonlocal failed
                if path.name == "work.txt" and path.parent.name.startswith(".sumo-restore-") and not failed:
                    failed = True
                    raise OSError("injected commit failure")
                return real_rename(path, target)
            with patch.object(Path, "rename", fail_once):
                with self.assertRaises(OSError):
                    revert(p, "valid")
            self.assertEqual((p / "work.txt").read_text(), "current")
            revert(p, "valid")
            self.assertEqual((p / "work.txt").read_text(), "old")
            self.assertTrue(any(f.read_text() == "current" for f in (p / "snapshots").glob("pre-restore-*/work.txt")))

    def test_no_evidence_no_readiness(self):
        result = verify_stage8({"ok": True, "mode": "exports_only"}, "", "", "")
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "not_verified")

    def test_stage8_requires_exact_evidence_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = [Path(tmp) / name for name in ("schematic", "dll", "state")]
            for path in paths:
                path.write_text(path.name)
            evidence = {"status": "completed", "runtime_validation": True,
                        **{f"{p.name}_sha256": hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}}
            record = Path(tmp) / "evidence.json"
            record.write_text(json.dumps(evidence))
            args = ({"ok": True, "refs_resolved": 1}, *(str(p) for p in paths), str(record))
            self.assertTrue(verify_stage8(*args)["ok"])
            paths[2].write_text("unrelated state")
            self.assertFalse(verify_stage8(*args)["ok"])

    def test_topology_requires_real_targets_and_ports(self):
        sch = {"units": [{"id": "u", "type": "influent"}], "connections": []}
        base = {"unit_ids": ["Influent1"], "connections": []}
        self.assertFalse(sumo_native.topology_match_report(sch, base, user_mapping={"u": "absent"})["ok"])
        self.assertTrue(sumo_native.topology_match_report(sch, base, user_mapping={"u": "Influent1"})["ok"])
        opaque = sumo_native.topology_match_report(sch, {"unit_ids": ["Influent1"]})
        self.assertFalse(opaque["ok"])
        self.assertTrue(opaque["parameter_mapping_ok"])
        sch["connections"] = [{"from": "u", "to": "u", "from_port": "out", "to_port": "in"}]
        self.assertFalse(sumo_native.topology_match_report(sch, base)["ok"])

    def test_missing_and_partial_values_are_not_exact_metrics(self):
        eff = academic_bundle._derive_effluent({})
        self.assertIsNone(eff["TN"])
        self.assertIsNone(eff["SCOD"])
        eff = academic_bundle._derive_effluent({"SNHx": 2, "SNO3": 3, "SNO2": 0})
        self.assertEqual(eff["inorganic_N_partial"], 5)
        self.assertIsNone(eff["TN"])
        self.assertIsNone(sumo_offline._unit_solids_sum({"Sumo__Plant__C__Xunknown": 42}, "C"))
        self.assertEqual(sumo_offline._unit_solids_sum({"Sumo__Plant__C__XTSS": 12}, "C"), 12)
        self.assertEqual(academic_bundle._plot_value(0), 0)
        self.assertNotEqual(academic_bundle._plot_value(None), academic_bundle._plot_value(None))


if __name__ == "__main__":
    unittest.main()
