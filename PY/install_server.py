"""Install the bundled DynaSand unit and register a verified MCP server.

Run from install.ps1 or sumo24-mcp-install. Interactive recovery is confined here;
the stdio server never calls input(). No license or vendor model is redistributed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from sumo_paths import resolve_install_dir

UNIT = "HH_DynaSand_v1"
CATEGORY = "SUMO24 MCP units"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def atomic_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def probe(install_dir: Path):
    """Check native adapter and actual stdio discovery before changing client config."""
    env = dict(os.environ, SUMO_INSTALL_DIR=str(install_dir), PYTHONPATH=os.pathsep.join((str(HERE), str(HERE.parent))), PYTHONUTF8="1")
    native = subprocess.run([sys.executable, "-c", "import dynamita.scheduler as d; print(d.sumo.getDLLVersion()); d.sumo.cleanup()"],
                            env=env, capture_output=True, text=True, timeout=40)
    if native.returncode:
        raise RuntimeError("Native SUMO check failed: " + native.stderr[-1600:])
    wire = subprocess.run([sys.executable, str(HERE / "installation_probe.py")], env=env,
                          capture_output=True, text=True, timeout=60)
    if wire.returncode:
        raise RuntimeError("MCP startup check failed: " + wire.stderr[-1600:])
    return {"native_version": native.stdout.strip(), "mcp": json.loads(wire.stdout)}


def legacy_files(overlay: Path, target: Path, bundle: Path) -> list[Path]:
    """Identify only previously shipped assets; never remove edited/custom files."""
    known = json.loads((bundle.parent / "legacy_dynasand.json").read_text(encoding="utf-8"))
    remove = []
    for workbook in (overlay / "Process Units").rglob(UNIT + ".xlsx"):
        if workbook.parent.resolve() == target.resolve():
            continue
        if digest(workbook) not in known[UNIT + ".xlsx"]:
            raise RuntimeError(f"A modified DynaSand already exists at {workbook}. Preserve/move it before migration; duplicate class names are unsafe.")
        remove.append(workbook)
        icon = workbook.with_suffix(".emf")
        if icon.exists() and digest(icon) in known.get(icon.name, []):
            remove.append(icon)
        # A group shared with another unit belongs to that unit too.
        others = [p for p in workbook.parent.glob("*.xlsx") if p != workbook and "Group Info" not in p.name]
        if not others:
            for group in workbook.parent.glob("* Group Info.xlsx"):
                if digest(group) in known.get(group.name, []):
                    remove.append(group)
    return remove


@contextmanager
def _setup_lock(config_path):
    """Serialize registrations across processes, including distinct SUMO installations."""
    path = Path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_name(path.name + ".sumo24.lock").open("a+b") as lock:
        lock.seek(0, os.SEEK_END)
        if not lock.tell():
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            lock.seek(0)
            if os.name == "nt":
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def install_once(sumo_dir=None, *, config_path: Path, data_dir: Path, project_dir: Path | None = None,
                 check=probe, bundle_dir: Path | None = None):
    install_dir = resolve_install_dir(sumo_dir, required=True)
    assert install_dir is not None
    import unit_installer
    # Hold both locks through overlay migration, ownership persistence and registration.
    with _setup_lock(config_path), unit_installer._THREAD_LOCK:
        unit_installer.configure_install_root(install_dir)
        os.environ["SUMO_INSTALL_DIR"] = str(install_dir)
        with unit_installer._overlay_lock():
            return _install_locked(install_dir, config_path=Path(config_path), data_dir=Path(data_dir),
                                   project_dir=project_dir, check=check, bundle_dir=bundle_dir)


def _install_locked(install_dir, *, config_path, data_dir, project_dir, check, bundle_dir):
    import unit_installer
    pending = [p for p in data_dir.glob('install-*/journal.json')
               if not (p.parent / 'committed').exists() and not (p.parent / 'rolled-back').exists()]
    if pending:
        raise RuntimeError('An interrupted server installation needs recovery before retry: ' +
                           ', '.join(str(p) for p in pending))
    bundle = bundle_dir or HERE / "bundled_units" / UNIT
    release = bundle.parent / "dynasand_release.json"
    import build_provenance
    verified = build_provenance.verify_release(bundle, release)
    if not verified["ok"]:
        raise RuntimeError("Bundled DynaSand validation failed: " + verified["reason"])
    config_before = config_path.read_bytes() if config_path.exists() else None
    existing = json.loads(config_before.decode("utf-8-sig")) if config_before is not None else {}
    if not isinstance(existing, dict) or not isinstance(existing.get("mcpServers", {}), dict):
        raise ValueError("Client config must contain an object named mcpServers")
    if project_dir is not None:
        project_dir = project_dir.resolve()
        for name in ("sumoproject.dll", "state.xml"):
            if not (project_dir / name).is_file():
                raise ValueError(f"Project directory is missing {name}: {project_dir}")
    checks = check(install_dir)
    overlay = install_dir / "Dir" / "My Process Code"
    target = overlay / "Process Units" / CATEGORY / "DynaSand"
    old = legacy_files(overlay, target, bundle)
    data_dir.mkdir(parents=True, exist_ok=True)
    source = data_dir / "units" / UNIT
    installed_manifest = source / unit_installer.MANIFEST_NAME
    managed = json.loads(installed_manifest.read_text(encoding="utf-8")) if installed_manifest.exists() else {}
    owned = {r["path"]: r["sha256"] for r in managed.get("files", [])}
    previous = {}
    for name in (UNIT + ".xlsx", UNIT + ".emf", "DynaSand Group Info.xlsx"):
        dest = target / name
        if dest.exists():
            previous[dest] = dest.read_bytes()
            if digest(dest) != digest(bundle / name) and owned.get(str(dest)) != digest(dest):
                raise RuntimeError(f"Refusing to replace an untracked or edited unit asset: {dest}")
    # This directory is unique and retained if rollback fails. Never overwrite older backups.
    transaction = Path(tempfile.mkdtemp(prefix="install-", dir=data_dir))
    stage = transaction / UNIT
    source_backup = transaction / "previous-source"
    moved = []
    result = None
    source_replaced = False
    source_backed_up = False
    config_attempted = False
    preserve_transaction = False
    try:
        shutil.copytree(bundle, stage)
        staged_release = transaction / release.name
        shutil.copy2(release, staged_release)
        if config_before is not None:
            (transaction / "previous-config.json").write_bytes(config_before)
        for i, (dest, content) in enumerate(previous.items()):
            (transaction / ("previous-unit-%d" % i)).write_bytes(content)
        atomic_json(transaction / "journal.json", {"config": str(config_path), "source": str(source),
                    "target": str(target), "previous_files": [str(p) for p in previous],
                    "legacy": [str(p) for p in old]})
        result = unit_installer.install_process_unit(stage, opt_in=True, unit_name=UNIT,
                    category=CATEGORY, allow_bulk=True, replace=True, release_manifest=staged_release)
        if not result.get("installed"):
            raise RuntimeError("DynaSand install failed: " + result.get("reason", str(result)))
        migration = transaction / "legacy-backup"
        for path in old:
            saved = migration / path.relative_to(overlay)
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, saved)
            moved.append((path, saved))
            path.unlink()
        env = {"SUMO_INSTALL_DIR": str(install_dir), "SUMO_OUTPUT": str(data_dir / "outputs"),
               "PYTHONPATH": os.pathsep.join((str(HERE), str(HERE.parent)))}
        project = project_dir or data_dir / "project"
        env.update(SUMO_DLL=str(project / "sumoproject.dll"), SUMO_STATE=str(project / "state.xml"))
        existing.setdefault("mcpServers", {})["sumo24"] = {"command": sys.executable,
                    "args": [str(HERE / "server.py")], "env": env}
        manifest_path = stage / unit_installer.MANIFEST_NAME
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["slug_dir"] = str(source)
        for record in manifest["files"]:
            record["source"] = str(source / Path(record["source"]).relative_to(stage))
        atomic_json(manifest_path, manifest)
        source.parent.mkdir(parents=True, exist_ok=True)
        if source.exists():
            os.replace(source, source_backup)
            source_backed_up = True
        os.replace(stage, source)
        source_replaced = True
        config_attempted = True
        atomic_json(config_path, existing)
        (transaction / "committed").write_text("complete", encoding="ascii")
        # Keep legacy/config/source backups as an audit trail, using a unique directory.
        preserve_transaction = bool(moved or source_backed_up or config_before is not None)
    except Exception as exc:
        recovery_errors = []
        def recover(operation):
            try:
                operation()
            except OSError as error:
                recovery_errors.append(str(error))
        if config_attempted:
            if config_before is None:
                recover(lambda: config_path.unlink(missing_ok=True))
            else:
                recover(lambda: config_path.write_bytes(config_before))
        if source_replaced:
            recover(lambda: shutil.rmtree(source))
        if source_backed_up:
            recover(lambda: os.replace(source_backup, source))
        if result and result.get("installed"):
            for file in result["files"]:
                dest = Path(file)
                if dest in previous:
                    recover(lambda dest=dest: dest.write_bytes(previous[dest]))
                else:
                    recover(lambda dest=dest: dest.unlink(missing_ok=True))
        for path, saved in moved:
            recover(lambda path=path, saved=saved: shutil.copy2(saved, path))
        preserve_transaction = bool(moved or recovery_errors)
        if recovery_errors:
            raise RuntimeError(f"Installation failed; rollback incomplete. Recovery files: {transaction}; {recovery_errors}") from exc
        (transaction / "rolled-back").write_text("complete", encoding="ascii")
        raise
    finally:
        if not preserve_transaction:
            shutil.rmtree(transaction, ignore_errors=True)
    return {"installed": True, "sumo_dir": str(install_dir), "config": str(config_path),
            "unit": UNIT, "category": CATEGORY, "family": "DynaSand", "destination": str(target),
            "migrated_files": [str(p) for p in old], "checks": checks,
            "backup_directory": str(transaction) if preserve_transaction else None,
            "next_step": "Restart SUMO and your MCP client. Configure a project before simulation."}


def install_with_retry(sumo_dir=None, *, interactive=True, ask=input, report=print, **kwargs):
    candidate = sumo_dir
    while True:
        try:
            return install_once(candidate, **kwargs)
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
            if not interactive:
                raise
            report(f"Installation did not complete: {exc}")
            try:
                candidate = ask("Enter your SUMO files directory (folder containing Sumo24.exe, or Process code); Enter cancels: ").strip()
            except (EOFError, KeyboardInterrupt):
                raise RuntimeError("Installation cancelled") from exc
            if not candidate:
                raise RuntimeError("Installation cancelled") from exc


def main():
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local/share"))) / "SUMO24MCP"
    default_config = Path(os.environ.get("APPDATA", str(Path.home() / ".config"))) / "Claude" / "claude_desktop_config.json"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sumo-dir", help="SUMO installation root or a folder inside it")
    parser.add_argument("--project-dir", type=Path, help="Optional extracted model with sumoproject.dll and state.xml")
    parser.add_argument("--config", type=Path, default=default_config, help="MCP mcpServers JSON config; existing entries preserved")
    parser.add_argument("--data-dir", type=Path, default=base)
    parser.add_argument("--non-interactive", action="store_true")
    args = parser.parse_args()
    try:
        result = install_with_retry(args.sumo_dir, interactive=not args.non_interactive,
                config_path=args.config.resolve(), data_dir=args.data_dir.resolve(), project_dir=args.project_dir)
    except Exception as exc:
        print(f"Installation failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
