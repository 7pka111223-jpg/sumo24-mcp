"""
pipeline/snapshot.py
────────────────────
Tar-based snapshots of the entire project directory (excluding the
snapshots/ sub-directory itself).

Every stage advance takes a snapshot BEFORE mutating the project so that
pipeline_revert can restore any earlier state.

Snapshots are pruned to KEEP=30 per project to avoid filling the disk.
"""
from __future__ import annotations

import pathlib
import shutil
import tarfile
import tempfile
from datetime import datetime

KEEP = 30  # maximum number of snapshots to retain per project


def snapshot(project_dir: "str | pathlib.Path", label: str) -> str:
    """
    Create a timestamped tar archive of project_dir (excluding snapshots/).
    Returns the archive path as a string.
    """
    pdir = pathlib.Path(project_dir)
    sdir = pdir / "snapshots"
    sdir.mkdir(parents=True, exist_ok=True)

    ts = datetime.utcnow().strftime("%Y-%m-%dT%H-%M-%S")
    out = sdir / f"{ts}_{label}.tar"

    with tarfile.open(out, "w") as t:
        for item in sorted(pdir.iterdir()):
            if item.name == "snapshots":
                continue
            t.add(item, arcname=item.name, recursive=True)

    prune(pdir)
    return str(out)


def list_snapshots(project_dir: "str | pathlib.Path") -> list[pathlib.Path]:
    """Return all snapshot tars sorted oldest → newest."""
    sdir = pathlib.Path(project_dir) / "snapshots"
    if not sdir.exists():
        return []
    return sorted(sdir.glob("*.tar"))


def revert(project_dir: "str | pathlib.Path", to_label_substring: str) -> str:
    """
    Restore from the latest snapshot whose filename contains to_label_substring.
    Validate and stage before replacing files. Retain the previous state in snapshots/.
    Returns the path of the snapshot that was restored.
    """
    matches = [
        p for p in list_snapshots(project_dir)
        if to_label_substring in p.name
    ]
    if not matches:
        raise FileNotFoundError(
            f"No snapshot matching {to_label_substring!r} in {project_dir}/snapshots/"
        )
    src = matches[-1]  # latest matching snapshot
    pdir = pathlib.Path(project_dir).resolve(strict=True)
    if pdir == pathlib.Path(pdir.anchor) or not (pdir / "project.yaml").is_file():
        raise ValueError("Restore requires an owned pipeline directory containing project.yaml")
    if (pdir / "snapshots").is_symlink() or src.is_symlink():
        raise ValueError("Snapshot paths must not be symbolic links")
    with tempfile.TemporaryDirectory(prefix=".sumo-restore-", dir=pdir.parent) as tmp:
        stage = pathlib.Path(tmp)
        with tarfile.open(src, "r") as archive:
            members = archive.getmembers()
            if not members:
                raise ValueError("Empty snapshot")
            for member in members:
                name = pathlib.PurePosixPath(member.name)
                if (name.is_absolute() or ".." in name.parts or "\\" in member.name
                        or ":" in member.name or not name.parts
                        or name.parts[0].lower() == "snapshots"
                        or not (member.isfile() or member.isdir())):
                    raise ValueError(f"Unsafe snapshot member: {member.name}")
                target = (stage / member.name).resolve()
                if not target.is_relative_to(stage):
                    raise ValueError(f"Snapshot member escapes staging directory: {member.name}")
            # Explicit path/type validation above is independent of tarfile defaults.
            archive.extractall(stage, members=members, filter="data")
        from .manifest import load
        restored_manifest = load(stage)  # validate before any current file is moved
        if not isinstance(restored_manifest, dict) or not restored_manifest.get("plant_name"):
            raise ValueError("Snapshot has no valid pipeline project manifest")
        backup = pathlib.Path(tempfile.mkdtemp(prefix="pre-restore-", dir=pdir / "snapshots"))
        moved, installed = [], []
        try:
            for item in list(pdir.iterdir()):
                if item.name != "snapshots":
                    item.rename(backup / item.name)
                    moved.append(item.name)
            for item in list(stage.iterdir()):
                item.rename(pdir / item.name)
                installed.append(item.name)
        except Exception:
            for name in reversed(installed):
                (pdir / name).rename(stage / name)
            for name in reversed(moved):
                (backup / name).rename(pdir / name)
            raise

    return str(src)


def prune(project_dir: "str | pathlib.Path") -> int:
    """Delete oldest snapshots until at most KEEP remain.  Returns number deleted."""
    snaps = list_snapshots(project_dir)
    n_removed = 0
    while len(snaps) > KEEP:
        snaps[0].unlink()
        snaps = snaps[1:]
        n_removed += 1
    return n_removed
