"""Server setup behavior against disposable SUMO layouts; no native execution."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'PY'))
import install_server as setup
import unit_installer
import build_provenance

class ServerInstallationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.sumo = self.root / 'SUMO'
        self.sumo.mkdir()
        for name in ('Sumo24.exe', 'sumoscheduler.dll'):
            (self.sumo / name).write_bytes(b'fixture')
        self.bundle = self.root / 'bundle' / setup.UNIT
        self.bundle.mkdir(parents=True)
        for name in (setup.UNIT + '.xlsx', setup.UNIT + '.emf', 'DynaSand Group Info.xlsx'):
            (self.bundle / name).write_bytes(('bundled ' + name).encode())
        self.release = self.bundle.parent / 'dynasand_release.json'
        self.release.write_text(json.dumps({'schema': 1, 'kind': 'source-release', 'release_id': 'test',
            'files': build_provenance.sources(self.bundle),
            'compiled_outputs': {'xml_sha256': 'a'*64, 'dll_sha256': 'b'*64}}))
        self.legacy = self.bundle.parent / 'legacy_dynasand.json'
        self.legacy.write_text(json.dumps({setup.UNIT + '.xlsx': [setup.digest(self.bundle / (setup.UNIT + '.xlsx'))]}))
        self.config = self.root / 'client.json'
        self.data = self.root / 'data'
        self.overlay = self.sumo / 'Dir' / 'My Process Code'
        self.target = self.overlay / 'Process Units' / setup.CATEGORY / 'DynaSand'
        self.original_root = unit_installer.INSTALL_ROOT
        self.environ = patch.dict(os.environ, {}, clear=False)
        self.environ.start()
    def tearDown(self):
        unit_installer.configure_install_root(self.original_root)
        self.environ.stop()
        self.tmp.cleanup()
    def install(self, **kwargs):
        return setup.install_once(self.sumo, config_path=self.config, data_dir=self.data,
            bundle_dir=self.bundle, check=lambda _: {'native': 'fixture'}, **kwargs)
    def test_install_and_retry_are_idempotent_preserve_other_servers(self):
        other = {'command': 'other.exe', 'args': ['--stay']}
        self.config.write_text(json.dumps({'mcpServers': {'other': other}, 'theme': 'dark'}))
        self.assertTrue(self.install()['installed'])
        first = (self.target / (setup.UNIT + '.xlsx')).read_bytes()
        self.assertTrue(self.install()['installed'])
        config = json.loads(self.config.read_text())
        self.assertEqual(config['mcpServers']['other'], other)
        self.assertEqual(config['theme'], 'dark')
        self.assertEqual((self.target / (setup.UNIT + '.xlsx')).read_bytes(), first)
        self.assertEqual(self.target.parent.name, 'SUMO24 MCP units')
    def test_directory_failure_prompts_and_retries(self):
        questions = []
        result = setup.install_with_retry(self.root / 'bad', ask=lambda q: questions.append(q) or str(self.sumo),
            report=lambda _: None, config_path=self.config, data_dir=self.data,
            bundle_dir=self.bundle, check=lambda _: {})
        self.assertTrue(result['installed'])
        self.assertEqual(len(questions), 1)
        self.assertIn('SUMO files directory', questions[0])
    def test_migration_preserves_shared_group_and_backup(self):
        old = self.overlay / 'Process Units' / '90 HH Custom' / 'HH Custom Units'
        old.mkdir(parents=True)
        unit = old / (setup.UNIT + '.xlsx')
        unit.write_bytes((self.bundle / unit.name).read_bytes())
        (old / 'OtherUnit.xlsx').write_bytes(b'keep other')
        (old / 'HH Custom Units Group Info.xlsx').write_bytes(b'keep group')
        result = self.install()
        self.assertFalse(unit.exists())
        self.assertTrue((old / 'OtherUnit.xlsx').exists())
        self.assertTrue((old / 'HH Custom Units Group Info.xlsx').exists())
        self.assertTrue(list(Path(result['backup_directory']).rglob(unit.name)))
    def test_edited_target_refused(self):
        self.install()
        workbook = self.target / (setup.UNIT + '.xlsx')
        workbook.write_bytes(b'user edits')
        before = self.config.read_bytes()
        with self.assertRaisesRegex(RuntimeError, 'edited unit asset'):
            self.install()
        self.assertEqual(workbook.read_bytes(), b'user edits')
        self.assertEqual(self.config.read_bytes(), before)
    def test_config_failure_restores_source_manifest_overlay_and_config(self):
        self.install()
        source = self.data / 'units' / setup.UNIT
        (source / 'extra-user-note.txt').write_bytes(b'keep note')
        before_source = {str(p.relative_to(source)): p.read_bytes() for p in source.rglob('*') if p.is_file()}
        before_config = self.config.read_bytes()
        before_overlay = {p.name: p.read_bytes() for p in self.target.iterdir() if p.is_file()}
        original = setup.atomic_json
        def fail_config(path, data):
            original(path, data)
            if path == self.config:
                raise OSError('injected after config replace')
        with patch.object(setup, 'atomic_json', side_effect=fail_config):
            with self.assertRaises(OSError):
                self.install()
        self.assertEqual(before_source, {str(p.relative_to(source)): p.read_bytes() for p in source.rglob('*') if p.is_file()})
        self.assertEqual(before_config, self.config.read_bytes())
        self.assertEqual(before_overlay, {p.name: p.read_bytes() for p in self.target.iterdir() if p.is_file()})
    def test_failed_fresh_registration_restores_legacy_and_retains_unique_backup(self):
        old = self.overlay / 'Process Units' / 'HH' / 'Old'
        old.mkdir(parents=True)
        unit = old / (setup.UNIT + '.xlsx')
        unit.write_bytes((self.bundle / unit.name).read_bytes())
        prior_backup = self.data / 'legacy-backup' / 'prior.txt'
        prior_backup.parent.mkdir(parents=True)
        prior_backup.write_bytes(b'prior backup')
        original = setup.atomic_json
        def fail_config(path, data):
            if path == self.config:
                raise OSError('injected config failure')
            original(path, data)
        with patch.object(setup, 'atomic_json', side_effect=fail_config):
            with self.assertRaises(OSError):
                self.install()
        self.assertTrue(unit.exists())
        self.assertFalse((self.target / unit.name).exists())
        self.assertFalse((self.data / 'units' / setup.UNIT).exists())
        self.assertEqual(prior_backup.read_bytes(), b'prior backup')
        self.assertTrue(list(self.data.glob('install-*/legacy-backup')))
    def test_malformed_config_does_not_install(self):
        self.config.write_text('{broken')
        with self.assertRaises(ValueError):
            self.install()
        self.assertFalse(self.target.exists())
        self.assertEqual(self.config.read_text(), '{broken')

if __name__ == '__main__':
    unittest.main()
