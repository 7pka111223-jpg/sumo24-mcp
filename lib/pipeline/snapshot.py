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
    Wipes all non-snapshots content of project_dir first, then extracts the archive.
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
    pdir = pathlib.Path(project_dir)

    # Wipe everything except snapshots/
    for item in pdir.iterdir():
        if item.name == "snapshots":
            continue
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()

    with tarfile.open(src, "r") as t:
        t.extractall(pdir)

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
