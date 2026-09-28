"""Record final package and installed-unit integrity without native execution."""
from pathlib import Path
import hashlib
import json
import sys
import zipfile
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'PY'))
import build_provenance
bundle = ROOT / 'PY/bundled_units/HH_DynaSand_v1'
destination = Path(r'D:\SUMO24\Dir\My Process Code\Process Units\SUMO24 MCP units\DynaSand')
installed = {}
for source in bundle.iterdir():
    if source.suffix in ('.xlsx', '.emf'):
        target = destination / source.name
        assert source.read_bytes() == target.read_bytes(), source.name
        installed[source.name] = build_provenance.sha(target)
assert not Path(r'D:\SUMO24\Dir\My Process Code\Process Units\90 HH Custom\HH Custom Units\HH_DynaSand_v1.xlsx').exists()
wheel = ROOT / 'dist/sumo24_mcp-0.2.0-py3-none-any.whl'
with zipfile.ZipFile(wheel) as archive:
    names = archive.namelist()
    assert not any(n.endswith(('.dll', '.sumo', '.dynlic', '.xlsm')) for n in names)
    for name in installed:
        assert archive.read('sumo24_mcp/bundled_units/HH_DynaSand_v1/' + name) == (bundle / name).read_bytes()
    assert 'sumo24_mcp/native_launch.py' in names
    assert 'sumo24_mcp/compiler_lock.py' in names
    assert 'sumo24_mcp/tool_registry.py' in names
result = {'ok': True, 'wheel': wheel.name, 'wheel_sha256': build_provenance.sha(wheel),
          'wheel_files': len(names), 'installed_category': 'SUMO24 MCP units', 'installed_family': 'DynaSand',
          'installed_files': installed, 'legacy_unit_removed': True,
          'source_release': build_provenance.verify_release(bundle, bundle.parent / 'dynasand_release.json')}
(ROOT / 'docs/reviews/implementation-2026-09-08/distribution-verification.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
print(json.dumps(result, indent=2))
