"""Content-bound build evidence. Digests detect stale inputs; they are not signatures."""
import hashlib
import json
from pathlib import Path

NAME = "build_provenance.json"

def attest_release(slug_dir, xml_path, dll_path, release_id, output_path):
    """Record source release evidence without redistributing native build outputs.

    The package maintainer must supply this trusted manifest explicitly at install time.
    This is a reproducibility record, not cryptographic authentication.
    """
    from slc_runner import verify_pe32plus
    if not verify_pe32plus(dll_path)['ok']:
        raise ValueError('release DLL is not a valid native image')
    data = {'schema': 1, 'kind': 'source-release', 'release_id': release_id,
            'files': sources(slug_dir),
            'compiled_outputs': {'xml_sha256': sha(xml_path), 'dll_sha256': sha(dll_path)}}
    Path(output_path).write_text(json.dumps(data, indent=2), encoding='utf-8')
    return data

def verify_release(slug_dir, manifest_path):
    try:
        data = json.loads(Path(manifest_path).read_text(encoding='utf-8'))
        if data.get('schema') != 1 or data.get('kind') != 'source-release' or not data.get('release_id'):
            raise ValueError('invalid release manifest')
        if sources(slug_dir) != data['files']:
            raise ValueError('bundled source differs from release build')
        outputs = data['compiled_outputs']
        if any(len(outputs[k]) != 64 or any(c not in '0123456789abcdef' for c in outputs[k])
               for k in ('xml_sha256', 'dll_sha256')):
            raise ValueError('missing release build digests')
        return {'ok': True, 'reason': 'bundled source release verified', 'release_id': data['release_id']}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {'ok': False, 'reason': str(exc)}

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def sources(root):
    root = Path(root).resolve()
    return {str(p.relative_to(root)): sha(p) for p in sorted(root.rglob('*'))
            if p.is_file() and (p.suffix.lower() in ('.xlsx', '.xlsm', '.emf') or p.name == 'unit_spec.json')}

def attest_bundle(slug_dir, xml_path, dll_path, release_id):
    """Explicit release-maintainer attestation after independent build validation."""
    root = Path(slug_dir).resolve()
    records = sources(root)
    for path in (xml_path, dll_path):
        p = Path(path).resolve()
        records[str(p.relative_to(root))] = sha(p)
    data = {'schema': 1, 'kind': 'bundled-release', 'release_id': release_id,
            'files': records, 'dll': str(Path(dll_path).resolve().relative_to(root)),
            'xml': str(Path(xml_path).resolve().relative_to(root))}
    (root / NAME).write_text(json.dumps(data, indent=2), encoding='utf-8')
    return data

def verify(slug_dir):
    root = Path(slug_dir).resolve()
    try:
        data = json.loads((root / NAME).read_text(encoding='utf-8'))
        if data.get('schema') != 1 or data.get('kind') not in ('bundled-release', 'compiler'):
            raise ValueError('unsupported build evidence')
        records = data['files']
        if not sources(root).items() <= records.items():
            raise ValueError('source/spec/workbook changed after build')
        for rel, digest in records.items():
            p = (root / rel).resolve()
            p.relative_to(root)
            if sha(p) != digest:
                raise ValueError('build input or output changed: ' + rel)
        for external, digest in data.get('external_files', {}).items():
            if sha(external) != digest:
                raise ValueError('external build dependency changed: ' + external)
        for key in ('dll', 'xml'):
            if data[key] not in records:
                raise ValueError('missing ' + key + ' digest')
        from slc_runner import verify_pe32plus
        pe = verify_pe32plus(root / data['dll'])
        if not pe['ok']:
            raise ValueError(pe['reason'])
        return {'ok': True, 'dll': str(root / data['dll']), 'reason': 'content-bound build verified'}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {'ok': False, 'reason': str(exc)}

def begin_smt(instance, xml, addpaths=(), compiler=None):
    Path(str(xml) + '.provenance.json').unlink(missing_ok=True)
    root = next((p for p in Path(instance).resolve().parents if (p / 'unit_spec.json').exists()), None)
    if root is None:
        return None
    external = {}
    for directory in addpaths or ():
        base = Path(directory).resolve()
        for relative, digest in sources(base).items():
            external[str(base / relative)] = digest
    if compiler:
        external[str(Path(compiler).resolve())] = sha(compiler)
    return {'root': str(root), 'files': sources(root), 'external_files': external}

def record_smt(instance, xml, snapshot=None):
    root = Path(snapshot['root']) if snapshot else None
    if root:
        if sources(root) != snapshot['files']:
            raise ValueError('sources changed during SMT execution')
        if any(sha(path) != digest for path, digest in snapshot.get('external_files', {}).items()):
            raise ValueError('external dependency changed during SMT execution')
        data = dict(snapshot, xml_sha256=sha(xml))
        Path(str(xml) + '.provenance.json').write_text(json.dumps(data), encoding='utf-8')

def record_link(xml, dll):
    sidecar = Path(str(xml) + '.provenance.json')
    if not sidecar.exists():
        return
    data = json.loads(sidecar.read_text(encoding='utf-8'))
    root = Path(data['root'])
    if sources(root) != data['files'] or sha(xml) != data['xml_sha256']:
        raise ValueError('sources changed between SMT and link')
    if any(sha(path) != digest for path, digest in data.get('external_files', {}).items()):
        raise ValueError('external dependency changed between SMT and link')
    result = attest_bundle(root, xml, dll, 'local-compiler')
    result['kind'] = 'compiler'
    result['external_files'] = data.get('external_files', {})
    (root / NAME).write_text(json.dumps(result, indent=2), encoding='utf-8')
