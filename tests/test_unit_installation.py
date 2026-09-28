"""Transactions use isolated fake overlays; no SUMO installation is modified."""
import json
import os
import sys
import tempfile
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "PY"))
import unit_installer as installer
import build_provenance

class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.old_root = installer.INSTALL_ROOT
        installer.configure_install_root(self.root / "sumo")
        installer.OVERLAY_ROOT.mkdir(parents=True)
        self.source = self.root / "source.xlsx"
        self.source.write_bytes(b"new workbook")
        self.dest = installer.OVERLAY_UNITS / "family" / "source.xlsx"
        self.manifest = self.root / "install_manifest.json"
    def tearDown(self):
        installer.configure_install_root(self.old_root)
        self.temp.cleanup()
    def test_replacement_restored_when_manifest_commit_fails(self):
        self.dest.parent.mkdir(parents=True)
        self.dest.write_bytes(b"previous workbook")
        self.manifest.write_bytes(b"previous manifest")
        real_replace = os.replace
        def fail_manifest(src, dst):
            if Path(src).name == "manifest":
                raise OSError("injected manifest failure")
            return real_replace(src, dst)
        with patch.object(installer.os, "replace", side_effect=fail_manifest):
            with self.assertRaises(OSError):
                installer._transaction([(self.source, self.dest)], self.manifest, {"files": []})
        self.assertEqual(self.dest.read_bytes(), b"previous workbook")
        self.assertEqual(self.manifest.read_bytes(), b"previous manifest")
    def test_fresh_install_restored_when_manifest_fails(self):
        real_replace = os.replace
        def fail_manifest(src, dst):
            if Path(src).name == "manifest":
                raise OSError("injected")
            return real_replace(src, dst)
        with patch.object(installer.os, "replace", side_effect=fail_manifest):
            with self.assertRaises(OSError):
                installer._transaction([(self.source, self.dest)], self.manifest, {})
        self.assertFalse(self.dest.exists())
        self.assertFalse(self.manifest.exists())
    def test_manifest_and_bytes_commit(self):
        installer._transaction([(self.source, self.dest)], self.manifest, {"ok": True})
        self.assertEqual(self.dest.read_bytes(), self.source.read_bytes())
        self.assertTrue(json.loads(self.manifest.read_text())["ok"])
    def test_macro_model_base_and_external_addpath_are_build_inputs(self):
        slug = self.root / 'slug'
        slug.mkdir()
        (slug / 'unit_spec.json').write_text('{}')
        instance = slug / 'Plant.xlsx'
        instance.write_bytes(b'plant')
        macro = slug / 'Model.xlsm'
        macro.write_bytes(b'macro-before')
        self.assertIn('Model.xlsm', build_provenance.sources(slug))
        external = self.root / 'dependency'
        external.mkdir()
        dependency = external / 'Base.xlsm'
        dependency.write_bytes(b'external-before')
        xml = slug / 'output.xml'
        snapshot = build_provenance.begin_smt(instance, xml, [external])
        xml.write_text('<model/>')
        dependency.write_bytes(b'external-after')
        with self.assertRaisesRegex(ValueError, 'external dependency'):
            build_provenance.record_smt(instance, xml, snapshot)
    def test_cross_drive_manifest_commit_uses_destination_volume(self):
        import errno
        replace = os.replace
        def cross_drive(src, dst):
            if Path(src).name == "manifest":
                raise OSError(errno.EXDEV, "different drive")
            return replace(src, dst)
        with patch.object(installer.os, "replace", side_effect=cross_drive):
            installer._transaction([(self.source, self.dest)], self.manifest, {"ok": True})
        self.assertTrue(json.loads(self.manifest.read_text())["ok"])
        self.assertEqual(self.dest.read_bytes(), self.source.read_bytes())
    def test_manifest_serialization_failure_leaves_old_bytes(self):
        self.dest.parent.mkdir(parents=True)
        self.dest.write_bytes(b'previous workbook')
        self.manifest.write_bytes(b'previous manifest')
        with self.assertRaises(TypeError):
            installer._transaction([(self.source, self.dest)], self.manifest, {'invalid': object()})
        self.assertEqual(self.dest.read_bytes(), b'previous workbook')
        self.assertEqual(self.manifest.read_bytes(), b'previous manifest')
    def test_outside_overlay_destination_rejected(self):
        victim = self.root / 'outside.xlsx'
        victim.write_bytes(b'keep')
        with self.assertRaises(installer.InstallPathError):
            installer._transaction([(self.source, victim)])
        self.assertEqual(victim.read_bytes(), b'keep')
    def test_uninstall_keeps_malicious_manifest_target(self):
        victim = self.root / 'outside.xlsx'
        victim.write_bytes(b'keep')
        self.manifest.write_text(json.dumps({'files': [{'path': str(victim),
            'sha256': installer._sha(victim)}], 'destination': str(self.root)}))
        result = installer.uninstall_process_unit(self.root, opt_in=True)
        self.assertFalse(result['uninstalled'])
        self.assertEqual(victim.read_bytes(), b'keep')
        self.assertEqual(len(result['kept']), 1)
        self.assertTrue(self.manifest.exists())
    def test_incomplete_journal_blocks_next_install(self):
        tx = installer.OVERLAY_ROOT / '.sumo24-mcp-tx-interrupted'
        tx.mkdir()
        (tx / 'journal.json').write_text('[]')
        with self.assertRaisesRegex(OSError, 'recovery journal'):
            with installer._overlay_lock():
                self.fail('must not allow writes over interrupted transaction')
        self.assertTrue((tx / 'journal.json').exists())
    def test_overlay_lock_excludes_another_process(self):
        script = ('import sys;sys.path.insert(0,sys.argv[1]);import unit_installer as u;'
                  'u.configure_install_root(sys.argv[2]);'
                  'ctx=u._overlay_lock();ctx.__enter__()')
        with installer._overlay_lock():
            result = subprocess.run([sys.executable, '-c', script,
                                     str(Path(installer.__file__).parent), str(installer.INSTALL_ROOT)],
                                    capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        with installer._overlay_lock():
            pass
    def test_arbitrary_dll_is_not_evidence(self):
        slug = self.root / "unit"
        (slug / "artifacts").mkdir(parents=True)
        (slug / "artifacts" / "anything.dll").write_bytes(b"fake")
        self.assertFalse(build_provenance.verify(slug)["ok"])
    def test_release_rejects_edited_equation_workbook(self):
        slug = self.root / "unit"
        slug.mkdir()
        wb = slug / "Unit.xlsx"
        wb.write_bytes(b"original equation")
        release = self.root / "release.json"
        release.write_text(json.dumps({"schema": 1, "kind": "source-release", "release_id": "test",
            "files": build_provenance.sources(slug),
            "compiled_outputs": {"xml_sha256": "a"*64, "dll_sha256": "b"*64}}))
        self.assertTrue(build_provenance.verify_release(slug, release)["ok"])
        wb.write_bytes(b"changed equation")
        self.assertFalse(build_provenance.verify_release(slug, release)["ok"])
    def test_build_manifest_cannot_reference_outside_slug(self):
        slug = self.root / 'unit'
        slug.mkdir()
        (slug / build_provenance.NAME).write_text(json.dumps({
            'schema': 1, 'kind': 'compiler', 'files': {'../source.xlsx': installer._sha(self.source)},
            'dll': '../source.xlsx', 'xml': '../source.xlsx'}))
        self.assertFalse(build_provenance.verify(slug)['ok'])

if __name__ == "__main__":
    unittest.main()
