"""
sumoslang_author.py
───────────────────
Group HH — custom SumoSlang process-unit authoring.

Ticket-16 scope: build cleanup and rollback primitives for the custom-unit
workspace layout (ticket 10):

    custom_units/<slug>/
        unit_spec.json      # single source of truth (ticket 13/05)
        build/              # SMT search root — DERIVED, regenerable
        artifacts/          # SMT XML, DLL, srcdir/, logs — DERIVED, regenerable
        snapshots/          # tar rollback store (pipeline.snapshot)

Derived dirs (build/, artifacts/) are always safe to delete: they are
regenerated from unit_spec.json + the read-only shipped library. Nothing a
plant references lives there. Rollback for the workspace is delegated to
PY/pipeline/snapshot.py (reused, not re-invented).
"""
from __future__ import annotations

import pathlib
import shutil

from pipeline import snapshot as _sn

BUILD_DIR = "build"
ARTIFACTS_DIR = "artifacts"
DERIVED_DIRS = (BUILD_DIR, ARTIFACTS_DIR)


def slug_dir(slug: "str | pathlib.Path") -> pathlib.Path:
    """Normalise a slug directory path (the custom_units/<slug> folder)."""
    return pathlib.Path(slug)


def clean_build(slug: "str | pathlib.Path") -> dict:
    """
    Wipe the derived build/ and artifacts/ directories under a slug.

    Idempotent: wiping an absent dir is a no-op. Safe without confirmation
    because every file in these two dirs is regenerated from unit_spec.json
    (plus the read-only shipped library). Never touches unit_spec.json or
    snapshots/.

    Returns {ok, removed, remaining}.
    """
    sd = slug_dir(slug)
    if not sd.is_dir():
        return {"ok": False, "error": f"not a directory: {sd}", "removed": [], "remaining": []}

    removed: list[str] = []
    for name in DERIVED_DIRS:
        target = sd / name
        if target.is_dir():
            shutil.rmtree(target)
            removed.append(name)
        elif target.exists():
            target.unlink()
            removed.append(name)

    remaining = sorted(
        p.name for p in sd.iterdir() if p.name != "snapshots"
    )
    return {"ok": True, "removed": removed, "remaining": remaining}


def snapshot_build(slug: "str | pathlib.Path", label: str) -> str:
    """
    Snapshot a slug directory before a build (reuses pipeline.snapshot).

    Store lives at <slug>/snapshots/, pruned to KEEP=30 per slug.
    Returns the archive path.
    """
    sd = slug_dir(slug)
    if not sd.is_dir():
        raise FileNotFoundError(f"not a directory: {sd}")
    return _sn.snapshot(sd, label)


def revert_build(slug: "str | pathlib.Path", to_label_substring: str) -> str:
    """
    Restore a slug directory from the latest snapshot matching a label.

    Wipes everything except snapshots/, then extracts. Any half-written
    build/ or artifacts/ from a failed run is removed by the wipe.
    Returns the restored archive path.
    """
    sd = slug_dir(slug)
    if not sd.is_dir():
        raise FileNotFoundError(f"not a directory: {sd}")
    return _sn.revert(sd, to_label_substring)

# =========================================================================== #
# Ticket 12 Phase C3 — naming, versioning and vendor-collision refusal
# (ticket 15). APPENDED to this module, which already holds ticket 16's
# cleanup/rollback surface above. Do not recreate this file.
# =========================================================================== #

import re as _re

CUSTOM_CATEGORY = "Custom"
HH_PREFIX = "HH_"
from sumo_paths import installation_path
_VENDOR_ROOT = installation_path("Process code", "Process units")
_NAME_RE = _re.compile(r"^HH_[A-Za-z0-9][A-Za-z0-9 _-]*_v[0-9]+$")


def qualified_name(base: str, version: int = 1) -> str:
    """`HH_<base>_v<n>` — the reserved prefix plus a mandatory version suffix (ticket 15)."""
    clean = _re.sub(r"[^A-Za-z0-9 _-]", "", str(base)).strip()
    if not clean:
        raise ValueError("unit base name is empty after sanitisation")
    if clean.startswith(HH_PREFIX):
        clean = clean[len(HH_PREFIX):]
    clean = _re.sub(r"_v\d+$", "", clean)
    return f"{HH_PREFIX}{clean}_v{int(version)}"


def is_well_formed(name: str) -> bool:
    return bool(_NAME_RE.match(name or ""))


def vendor_unit_names(root: "str | pathlib.Path | None" = None) -> "set[str]":
    """Every shipped unit workbook stem in the vendor library (read-only scan)."""
    r = pathlib.Path(root) if root else _VENDOR_ROOT
    if not r.exists():
        return set()
    return {p.stem for p in r.rglob("*.xlsx")
            if not p.name.startswith("~$") and "Group Info" not in p.name}


def check_collision(name: str, root: "str | pathlib.Path | None" = None) -> dict:
    """HARD ERROR on a vendor-name collision. This is load-bearing, not cosmetic.

    `-addpath` resolution is FIRST-FOUND-WINS and the SMT **silently shadows** a shipped unit
    with a staged one of the same relative path - no warning, no error, and the emitted XML
    reflects the wrong unit (ticket 10). This refusal is the only thing standing between a user
    and a plant compiled against the wrong process code, so it returns a refusal rather than a
    warning, and it checks the BARE name too: `HH_CSTR_v1` is safe, but a unit emitted as
    `Simple CSTR` would shadow the vendor's.
    """
    shipped = vendor_unit_names(root)
    bare = _re.sub(r"^HH_", "", _re.sub(r"_v\d+$", "", name or ""))

    # TWO DISTINCT COLLISIONS, with different mechanisms and different severity. Conflating
    # them means giving a true refusal a false reason, which is its own defect.
    if name in shipped:
        # Same workbook STEM -> same relative path under a search root -> real shadowing.
        return {"ok": False, "collision": "exact",
                "reason": f"name is IDENTICAL to a shipped vendor unit: {name!r}",
                "detail": ["-addpath resolution is first-found-wins and the SMT SILENTLY "
                           "shadows the shipped unit - no warning, and the emitted XML "
                           "reflects the wrong process code (ticket 10).",
                           "Choose a different base name; do not version around this."]}
    if bare in shipped:
        # Different filename, so NO shadowing is possible. The risk is human: two units whose
        # displayed names differ only by the HH_ prefix and version suffix.
        return {"ok": False, "collision": "bare-name",
                "reason": f"base name matches a shipped vendor unit: {bare!r}",
                "detail": [f"The emitted file would be {name}.xlsx, which CANNOT shadow "
                           f"{bare}.xlsx - the filenames differ, so -addpath is not involved.",
                           "This is refused for human ambiguity, not for shadowing: two units "
                           "differing only by the HH_ prefix and version are easy to confuse "
                           "on the drawing board and in results.",
                           "Ticket 15 (user decision): hard error, naming the shipped unit."]}
    if not is_well_formed(name):
        return {"ok": False, "collision": False,
                "reason": f"name {name!r} is not of the form HH_<name>_v<n>",
                "detail": ["ticket 15: reserved HH_ prefix and a mandatory version suffix"]}
    return {"ok": True, "collision": False, "reason": "no collision; name well-formed"}


def allocate_slug(base: str, custom_root: "str | pathlib.Path" = "custom_units",
                  version: "int | None" = None,
                  vendor_root: "str | pathlib.Path | None" = None) -> dict:
    """Pick the next free `HH_<base>_v<n>` folder. NEVER overwrites (ticket 15)."""
    root = pathlib.Path(custom_root)
    if version is not None:
        name = qualified_name(base, version)
        coll = check_collision(name, vendor_root)
        if not coll["ok"]:
            return {"allocated": False, **coll}
        target = root / name
        if target.exists():
            return {"allocated": False, "ok": False, "collision": False,
                    "reason": f"{target} already exists; refusing to overwrite",
                    "detail": ["ticket 15: never overwrite. Emit a new version instead."]}
        return {"allocated": True, "name": name, "path": str(target),
                "category": CUSTOM_CATEGORY}
    n = 1
    while n < 1000:
        name = qualified_name(base, n)
        coll = check_collision(name, vendor_root)
        if not coll["ok"] and coll.get("collision"):
            return {"allocated": False, **coll}
        if not (root / name).exists():
            return {"allocated": True, "name": name, "path": str(root / name),
                    "category": CUSTOM_CATEGORY, "version": n}
        n += 1
    return {"allocated": False, "ok": False, "reason": "exhausted 999 versions"}
