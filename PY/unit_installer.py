"""
unit_installer.py — Group HH, ticket 12 Phase G3: the ONLY writer into `D:\\SUMO24`.

Everything else in Group HH authors, compiles and tests inside the workspace and reaches the
shipped library only through `-addpath`. [MEASURED, ticket 10] That guarantee is not assumed:
a full build cycle left `D:\\SUMO24\\Process code\\` - **1,141 files - byte-identical**. This
module is the single, explicit, opt-in exception, and it is written so that guarantee survives.

WHERE IT WRITES, AND WHY NOT WHERE YOU MIGHT EXPECT

    D:\\SUMO24\\Dir\\My Process Code\\Process Units\\<category>\\<family>\\   <- units
    D:\\SUMO24\\Dir\\My Process Code\\Model base\\My Model Category\\         <- Type B forks

[MEASURED 2026-09-07, HH_DynaSand_v1] The palette layout above is NOT optional. Sumo's
startup scanner treats every `<family> Group Info.xlsx` as a multi-PU group whose members
are the SIBLING workbooks in the same folder (vendor pattern, e.g.
`30 Separators\\Sand filter\\Sand filter group info.xlsx` with the unit xlsx beside it). A
Group Info one level up with the workbook nested deeper parses fine and is then dropped:
`[SETUP] Empty multi-pu interface ... There is no model behind the title`. The installer
therefore maps ANY source layout onto `category\\<family>\\` where `<family>` is the Group
Info stem minus " Group Info" (falling back to the unit name when no Group Info exists).

**Not** `D:\\SUMO24\\Process code\\`. That is the vendor tree, it is the thing ticket 10 proved
untouched, and SUMO ships an empty user overlay for exactly this purpose - `My Process Code`
with `Process Units\\My Process Unit Category\\` and `Model base\\My Model Category\\` already
present and empty. Ticket 04 found the same slot documented as Dynamita's own procedure for a
forked model base. Installing into the vendor tree would work and would destroy the one
guarantee that makes this whole toolchain safe to run.

`_assert_overlay()` enforces it structurally: every write path is resolved and checked to be
under the overlay root before a single byte is written. A bug that computed a vendor-tree path
raises rather than writing.

WHAT IT REFUSES, and why each refusal is not paperwork:

  * **No opt-in -> refuse.** The user decision (Q10) was that exactly one step writes to the
    install, and it is explicit.

  * **Name collision -> HARD ERROR** (ticket 15, `sumoslang_author.check_collision`). [MEASURED,
    ticket 10] Resolution is first-found-wins and the SMT **silently shadows**: a staged
    `Simple CSTR` with `L.Vtrain=12345` was read instead of the shipped one, the XML carried
    12345, and nothing anywhere reported a problem. Installing a colliding name makes that
    permanent and invisible.

  * **Never compiled -> refuse.** Installing a unit that has never reached a DLL puts a unit on
    the drawing board that fails the first time anyone uses it. Overridable, deliberately, with
    `allow_uncompiled=True`.

  * **Spec not accepted -> refuse.** If the slug carries a `unit_spec.json`, the rung-1 emission
    gate is re-run here. `may_emit()` is called, not trusted to have been called earlier.

  * **Existing installation -> refuse unless `replace=True`.** Ticket 15: always a new version,
    never a silent overwrite. A plant compiled against `_v1` must keep compiling.

EVERY INSTALL WRITES A MANIFEST, and uninstall removes exactly what the manifest lists - never
a directory tree by pattern. Removing files the installer did not write is how a "cleanup" eats
someone's work.

OPERATIONAL FACT THE CALLER MUST BE TOLD: [READ, ticket 14] **the GUI re-scans the merged tree
at STARTUP ONLY.** An installed unit does not appear until SUMO is restarted, and there is no
live refresh to wait on. Every successful result says so.
"""
from __future__ import annotations

import datetime
import json
import pathlib
import shutil
import sys
import os
import tempfile
import inspect
import threading
from contextlib import contextmanager
from functools import wraps

_HERE = pathlib.Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import sumoslang_author
try:
    import spec_review
except Exception:                                            # pragma: no cover
    spec_review = None

INSTALL_ROOT = pathlib.Path(r"D:\SUMO24")
OVERLAY_ROOT = pathlib.Path(r"D:\SUMO24\Dir\My Process Code")
OVERLAY_UNITS = OVERLAY_ROOT / "Process Units"
OVERLAY_MODEL_BASE = OVERLAY_ROOT / "Model base"
VENDOR_TREE = INSTALL_ROOT / "Process code"
# SUMO renders the category directory verbatim, including any numeric prefix.
DEFAULT_CATEGORY = "SUMO24 MCP units"
DEFAULT_MODEL_CATEGORY = "My Model Category"
MANIFEST_NAME = "install_manifest.json"
_GROUP_INFO_SUFFIX = " Group Info.xlsx"
_THREAD_LOCK = threading.RLock()
_LOCK_STATE = threading.local()


def configure_install_root(root):
    """Configure the target resolved by the server installer (also supports isolated tests)."""
    global INSTALL_ROOT, OVERLAY_ROOT, OVERLAY_UNITS, OVERLAY_MODEL_BASE, VENDOR_TREE
    INSTALL_ROOT = pathlib.Path(root).resolve()
    OVERLAY_ROOT = INSTALL_ROOT / 'Dir' / 'My Process Code'
    OVERLAY_UNITS = OVERLAY_ROOT / 'Process Units'
    OVERLAY_MODEL_BASE = OVERLAY_ROOT / 'Model base'
    VENDOR_TREE = INSTALL_ROOT / 'Process code'


@contextmanager
def _overlay_lock():
    """OS advisory lock, released even when the installing process exits."""
    if getattr(_LOCK_STATE, 'root', None) == OVERLAY_ROOT.resolve():
        yield
        return
    OVERLAY_ROOT.mkdir(parents=True, exist_ok=True)
    with (OVERLAY_ROOT / '.sumo24-mcp-install.lock').open('a+b') as lock:
        lock.seek(0, os.SEEK_END)
        if not lock.tell():
            lock.write(b'0')
            lock.flush()
        lock.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            pending = [p for p in OVERLAY_ROOT.glob('.sumo24-mcp-tx-*/journal.json')
                       if not (p.parent / 'committed').exists()]
            if pending:
                raise OSError('unfinished installation recovery journal requires inspection: ' +
                              ', '.join(str(p) for p in pending))
            _LOCK_STATE.root = OVERLAY_ROOT.resolve()
            yield
        finally:
            _LOCK_STATE.root = None
            lock.seek(0)
            if os.name == 'nt':
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _locked(operation):
    @wraps(operation)
    def run(*args, **kwargs):
        with _THREAD_LOCK:
            return invoke(*args, **kwargs)
    def invoke(*args, **kwargs):
        # Resolve lazily so an installation discovered after server import takes effect.
        if os.environ.get('SUMO_INSTALL_DIR'):
            try:
                from sumo_paths import resolve_install_dir
                configure_install_root(resolve_install_dir(required=True))
            except (OSError, ValueError, RuntimeError) as exc:
                key = 'uninstalled' if operation.__name__.startswith('uninstall') else 'installed'
                return {key: False, 'reason': 'SUMO directory is invalid: ' + str(exc),
                        'needs_sumo_directory': True}
        bound = inspect.signature(operation).bind(*args, **kwargs).arguments
        if not bound.get('opt_in', False) or bound.get('dry_run', False):
            return operation(*args, **kwargs)
        try:
            with _overlay_lock():
                return operation(*args, **kwargs)
        except OSError as exc:
            key = 'uninstalled' if operation.__name__.startswith('uninstall') else 'installed'
            return {key: False, 'reason': 'overlay unavailable or another installation is running: ' + str(exc)}
    return run


def _replace_across_volumes(source, destination):
    """Atomic destination replacement even when the journal lives on another drive."""
    try:
        os.replace(source, destination)
    except OSError as exc:
        import errno
        if exc.errno != errno.EXDEV and getattr(exc, 'winerror', None) != 17:
            raise
        fd, temporary = tempfile.mkstemp(prefix='.sumo24-commit-', dir=pathlib.Path(destination).parent)
        os.close(fd)
        try:
            shutil.copy2(source, temporary)
            os.replace(temporary, destination)
        finally:
            pathlib.Path(temporary).unlink(missing_ok=True)


def _transaction(planned, manifest_path=None, manifest=None):
    """Stage all bytes and backups before replacing any destination; journal each path.

    Failed rollback keeps its journal/backups for manual recovery and reports that path.
    The manifest is part of the same transaction, including its previous contents.
    """
    tx = _assert_overlay(pathlib.Path(tempfile.mkdtemp(prefix='.sumo24-mcp-tx-', dir=OVERLAY_ROOT)))
    records = []
    committed = []
    try:
        for i, (src, dst) in enumerate(planned):
            dst = _assert_overlay(dst)
            staged = tx / ('stage-%d' % i)
            shutil.copy2(src, staged)
            records.append({'destination': str(dst), 'stage': str(staged)})
        if manifest_path is not None:
            staged = tx / 'manifest'
            staged.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
            records.append({'destination': str(pathlib.Path(manifest_path).resolve()), 'stage': str(staged)})
        for i, rec in enumerate(records):
            dst = pathlib.Path(rec['destination'])
            rec['existed'] = dst.exists()
            rec['backup'] = str(tx / ('backup-%d' % i))
            if dst.exists():
                shutil.copy2(dst, rec['backup'])
        (tx / 'journal.json').write_text(json.dumps(records, indent=2), encoding='utf-8')
        for rec in records:
            dst = pathlib.Path(rec['destination'])
            dst.parent.mkdir(parents=True, exist_ok=True)
            committed.append(rec)
            _replace_across_volumes(rec['stage'], dst)
        (tx / 'committed').write_text('complete', encoding='ascii')
    except Exception as exc:
        failures = []
        for rec in reversed(committed):
            try:
                dst = pathlib.Path(rec['destination'])
                if rec['existed']:
                    _replace_across_volumes(rec['backup'], dst)
                else:
                    dst.unlink(missing_ok=True)
            except OSError as recovery:
                failures.append(str(recovery))
        if failures:
            raise RuntimeError('rollback incomplete; recovery journal at %s: %s' % (tx, failures)) from exc
        shutil.rmtree(tx, ignore_errors=True)
        raise
    shutil.rmtree(tx, ignore_errors=True)


class InstallPathError(Exception):
    """A computed write path escaped the overlay. Programmer error, never a policy refusal."""


def _assert_overlay(p: pathlib.Path) -> pathlib.Path:
    """Every write goes through here. Refuses anything outside the user overlay."""
    rp = pathlib.Path(p).resolve()
    try:
        rp.relative_to(OVERLAY_ROOT.resolve())
    except ValueError:
        raise InstallPathError(
            "refusing to write outside the user overlay: %s (overlay is %s). The vendor tree "
            "at %s is READ-ONLY and was measured byte-identical after a full build cycle."
            % (rp, OVERLAY_ROOT, VENDOR_TREE))
    return rp


def _now() -> str:
    return datetime.datetime.now().replace(microsecond=0).isoformat()


def _sha(p: pathlib.Path) -> str:
    import hashlib
    return hashlib.sha256(p.read_bytes()).hexdigest()


# --------------------------------------------------------------------------- #
# Pre-flight
# --------------------------------------------------------------------------- #

def _find_slug(slug: str | pathlib.Path,
               custom_root: str | pathlib.Path = "custom_units") -> pathlib.Path | None:
    p = pathlib.Path(slug)
    if p.is_dir():
        return p
    p2 = pathlib.Path(custom_root) / str(slug)
    return p2 if p2.is_dir() else None


def _locate_group_info(unit_dir: pathlib.Path, pu_root: pathlib.Path | None) -> pathlib.Path | None:
    """[MEASURED 2026-09-07] The Group Info must be a SIBLING of the unit workbooks inside
    the family folder (vendor pattern). Accept the sibling first, then the legacy
    category-level layout, then anywhere in the staged build tree (the slug-root emission
    case)."""
    for scope in (unit_dir.glob("*" + _GROUP_INFO_SUFFIX),
                  unit_dir.parent.glob("*" + _GROUP_INFO_SUFFIX),
                  pu_root.rglob("*" + _GROUP_INFO_SUFFIX) if pu_root and pu_root.exists() else []):
        hits = sorted(scope)
        if hits:
            return hits[0]
    return None


def preflight(slug_dir: pathlib.Path, unit_name: str | None = None,
              allow_uncompiled: bool = False, allow_bulk: bool = False,
              release_manifest: str | pathlib.Path | None = None) -> dict:
    """Everything that must be true BEFORE a byte is written. Returns a verdict, never raises."""
    build = slug_dir / "build"
    art = slug_dir / "artifacts"

    # locate the unit folder inside the staged build tree, or the slug root itself
    # (hh_emit_unit_workbook writes the workbook directly into the slug)
    pu_root = build / "Process units"
    wb_hits: list[tuple[pathlib.Path, pathlib.Path]] = [
        (d, d / (d.name + ".xlsx")) for d in
        (pu_root.rglob("*") if pu_root.exists() else [])
        if d.is_dir() and (d / (d.name + ".xlsx")).exists()]
    if unit_name:
        wb_hits = [(d, w) for d, w in wb_hits if d.name == unit_name]
    if not wb_hits:
        # slug-root emission: <qualified_name>.xlsx (or a single unambiguous workbook)
        spec_name = None
        spec_path = slug_dir / "unit_spec.json"
        if spec_path.exists():
            try:
                ident = (json.loads(spec_path.read_text(encoding="utf-8")).get("identity") or {})
                spec_name = ident.get("qualified_name") or ident.get("name")
            except Exception:
                spec_name = None
        spec_name = unit_name or spec_name
        root_wb = (slug_dir / (spec_name + ".xlsx")) if spec_name else None
        if root_wb is None or not root_wb.exists():
            root_wbs = [p for p in sorted(slug_dir.glob("*.xlsx"))
                        if _GROUP_INFO_SUFFIX not in p.name and not p.name.startswith("~$")]
            root_wb = root_wbs[0] if len(root_wbs) == 1 and not unit_name else None
        if root_wb is not None and root_wb.exists():
            wb_hits = [(slug_dir, root_wb)]  # the slug root doubles as the unit folder
    if not wb_hits:
        return {"ok": False, "reason": "no unit folder found under %s (or workbook in the "
                "slug root)" % pu_root,
                "detail": ["A unit folder is <name>/<name>.xlsx - emit it with "
                           "hh_emit_unit_workbook before installing."]}
    if len(wb_hits) > 1 and not unit_name:
        return {"ok": False,
                "reason": "%d unit folders found; name one explicitly" % len(wb_hits),
                "detail": [d.name for d, _ in wb_hits]}
    unit_dir, workbook = wb_hits[0]
    name = workbook.stem

    checks: list[dict] = []
    checks.append({"check": "unit workbook", "ok": workbook.exists(), "path": str(workbook)})

    icon = unit_dir / (name + ".emf")
    if not icon.exists():
        icon = slug_dir / (name + ".emf")
    # [READ, ticket 14] `.emf` appears 0 times in the SMT XML and in the compiled project XML:
    # a missing icon can never break a compile, worst case is a blank glyph. So this is a
    # WARNING, and calling it a failure would block installs on artwork nobody is tasked with.
    checks.append({"check": "icon (.emf)", "ok": True, "warn": not icon.exists(),
                   "path": str(icon),
                   "note": "GUI-only; a missing icon cannot break a compile (ticket 14)"})

    group_info = _locate_group_info(unit_dir, pu_root)
    checks.append({"check": "Group Info", "ok": True, "warn": not group_info,
                   "path": str(group_info) if group_info else "(none)",
                   "note": "without it the group has no SortingPriority/DefaultUnit and the "
                           "GUI cannot resolve the palette entry (ticket 14); it must be a "
                           "SIBLING of the unit workbooks in the family folder "
                           "[measured 2026-09-07]"})

    import build_provenance
    evidence = (build_provenance.verify_release(slug_dir, release_manifest)
                if release_manifest else build_provenance.verify(slug_dir))
    compiled = evidence["ok"]
    dlls = [pathlib.Path(evidence["dll"])] if evidence.get("dll") else []
    checks.append({"check": "compiled provenance", "ok": compiled or allow_uncompiled,
                   "warn": not compiled and allow_uncompiled,
                   "note": evidence["reason"]})

    # rung 1 emission gate, re-run here rather than trusted
    spec_path = slug_dir / "unit_spec.json"
    if spec_path.exists() and spec_review is not None:
        try:
            spec = json.loads(spec_path.read_text(encoding="utf-8"))
            # `allow_bulk` mirrors the emission decision. Without the pass-through, a unit
            # legitimately emitted under a bulk confirmation would be refused HERE - a gate
            # that disagrees with the gate upstream of it is a bug, not extra safety.
            gate = spec_review.may_emit(spec, allow_bulk=allow_bulk)
            checks.append({"check": "rung-1 emission gate", "ok": bool(gate["may_emit"]),
                           "path": str(spec_path), "note": gate.get("reason", "")})
        except Exception as e:
            checks.append({"check": "rung-1 emission gate", "ok": False,
                           "path": str(spec_path),
                           "note": "spec unreadable: %s: %s" % (type(e).__name__, e)})
    elif spec_path.exists():
        checks.append({"check": "rung-1 emission gate", "ok": False,
                       "note": "spec_review is unavailable; acceptance cannot be verified"})
    else:
        checks.append({"check": "rung-1 emission gate", "ok": True, "warn": True,
                       "path": str(spec_path),
                       "note": "no unit_spec.json in the slug - the acceptance gate could not "
                               "be re-run, so acceptance is UNVERIFIED here"})

    collision = sumoslang_author.check_collision(name, root=VENDOR_TREE)
    checks.append({"check": "vendor name collision (ticket 15)", "ok": bool(collision["ok"]),
                   "path": name, "note": collision["reason"]})

    failed = [c for c in checks if not c["ok"]]
    return {"ok": not failed, "unit_name": name, "unit_dir": str(unit_dir),
            "workbook": str(workbook), "icon": str(icon) if icon.exists() else None,
            "group_info": str(group_info) if group_info else None,
            "dll": str(dlls[0]) if dlls else None, "compiled": compiled,
            "checks": checks,
            "warnings": [c for c in checks if c.get("warn")],
            "reason": "preflight clean" if not failed else
                      "; ".join("%s: %s" % (c["check"], c.get("note") or "failed")
                                for c in failed)}


# --------------------------------------------------------------------------- #
# Install / uninstall
# --------------------------------------------------------------------------- #

@_locked
def install_process_unit(slug: str | pathlib.Path,
                         opt_in: bool = False,
                         unit_name: str | None = None,
                         category: str = DEFAULT_CATEGORY,
                         custom_root: str | pathlib.Path = "custom_units",
                         allow_uncompiled: bool = False,
                         allow_bulk: bool = False,
                         replace: bool = False,
                         dry_run: bool = False,
                         release_manifest: str | pathlib.Path | None = None) -> dict:
    """Install a built unit into the SUMO user overlay. Refusals are return values."""
    if not opt_in:
        return {"installed": False, "reason": "opt_in is required",
                "detail": ["This is the only tool in Group HH that writes into %s."
                           % INSTALL_ROOT,
                           "Everything else stages into the workspace and reaches the shipped "
                           "library read-only through -addpath.",
                           "Pass opt_in=true to proceed; add dry_run=true to see the exact "
                           "file list first."]}

    slug_dir = _find_slug(slug, custom_root)
    if slug_dir is None:
        return {"installed": False, "reason": "slug directory not found: %s" % slug}

    pre = preflight(slug_dir, unit_name, allow_uncompiled=allow_uncompiled,
                    allow_bulk=allow_bulk, release_manifest=release_manifest)
    if not pre["ok"]:
        return {"installed": False, "reason": "preflight refused: " + pre["reason"],
                "preflight": pre}

    unit_dir = pathlib.Path(pre["unit_dir"])
    name = pre["unit_name"]

    # [MEASURED 2026-09-07] The palette group is the FAMILY folder and its members are the
    # SIBLING workbooks; the Group Info names the family. Map any source layout onto
    # category/<family>/ with the Group Info beside the workbook.
    gi = pre.get("group_info")
    family = pathlib.Path(gi).name[:-len(_GROUP_INFO_SUFFIX)] if gi else name
    try:
        dest_family = _assert_overlay(OVERLAY_UNITS / category / family)
    except InstallPathError as e:
        return {"installed": False, "reason": str(e)}

    planned: list[tuple[pathlib.Path, pathlib.Path]] = []
    for key in ("workbook", "icon", "group_info"):
        src = pre.get(key)
        if src and pathlib.Path(src).exists():
            planned.append((pathlib.Path(src), dest_family / pathlib.Path(src).name))
    if not planned:
        return {"installed": False, "reason": "nothing to install (no workbook/icon/group "
                "info could be located)"}

    existing = [str(d) for _, d in planned if d.exists()]
    if existing and not replace:
        return {"installed": False,
                "reason": "%s is already installed" % name,
                "detail": ["Ticket 15: always a new version, never an overwrite. A plant "
                           "compiled against this version must keep compiling.",
                           "Emit %s and install that, or pass replace=true deliberately."
                           % sumoslang_author.qualified_name(name, 2),
                           "Installed at: %s" % ", ".join(existing)]}

    if dry_run:
        return {"installed": False, "dry_run": True, "reason": "dry run - nothing written",
                "unit_name": name, "destination": str(dest_family),
                "would_write": [str(d) for _, d in planned],
                "preflight": pre}

    written = [{"path": str(dst), "sha256": _sha(src), "source": str(src),
                "overwrote_existing": dst.exists()} for src, dst in planned]
    manifest = {"installed_at": _now(), "unit_name": name, "category": category,
                "family": family, "slug_dir": str(slug_dir),
                "destination": str(dest_family), "overlay_root": str(OVERLAY_ROOT),
                "files": written, "dll_at_install": pre.get("dll"),
                "compiled": pre.get("compiled", False)}
    try:
        _transaction(planned, slug_dir / MANIFEST_NAME, manifest)
    except Exception as e:
        return {"installed": False, "reason": "install transaction failed: %s: %s" %
                (type(e).__name__, e)}

    return {
        "installed": True, "reason": "ok", "unit_name": name,
        "destination": str(dest_family), "n_files": len(written),
        "files": [w["path"] for w in written],
        "manifest": str(slug_dir / MANIFEST_NAME),
        "vendor_tree_untouched": str(VENDOR_TREE),
        "warnings": [c.get("note") for c in pre.get("warnings", [])],
        "IMPORTANT": "SUMO re-scans the merged process-code tree at STARTUP ONLY. This unit "
                     "will not appear on the drawing board until SUMO is restarted; there is "
                     "no live refresh to wait for.",
        "uninstall": "hh_install_process_unit is reversible: uninstall_process_unit(slug) "
                     "removes exactly the files this manifest lists.",
    }


@_locked
def install_model_base(fork_path: str | pathlib.Path, opt_in: bool = False,
                       category: str = DEFAULT_MODEL_CATEGORY,
                       replace: bool = False, dry_run: bool = False) -> dict:
    """Install a verified Type B model-base fork into the overlay's model-base slot."""
    if not opt_in:
        return {"installed": False, "reason": "opt_in is required",
                "detail": ["This writes into %s." % INSTALL_ROOT]}
    src = pathlib.Path(fork_path)
    if not src.exists():
        return {"installed": False, "reason": "fork not found: %s" % src}

    import model_base_fork
    shipped = model_base_fork.shipped_model_bases()
    if src.stem in shipped:
        return {"installed": False, "reason":
                "%r is the name of a SHIPPED model base; installing it would shadow the "
                "vendor's with nothing reporting it" % src.stem}

    try:
        dest_dir = _assert_overlay(OVERLAY_MODEL_BASE / category)
        dest = _assert_overlay(dest_dir / src.name)
    except InstallPathError as e:
        return {"installed": False, "reason": str(e)}

    if dest.exists() and not replace:
        return {"installed": False, "reason": "%s is already installed at %s" % (src.name, dest),
                "detail": ["A new state variable changes the compiled symbol table and "
                           "invalidates saved states (ticket 04). Replacing a model base under "
                           "plants that use it is exactly the silent breakage the additive-only "
                           "gate exists to prevent."]}
    if dry_run:
        return {"installed": False, "dry_run": True, "would_write": [str(dest)]}

    try:
        _transaction([(src, dest)])
    except Exception as exc:
        return {"installed": False, "reason": "model install transaction failed: " + str(exc)}
    return {"installed": True, "reason": "ok", "model_name": src.stem,
            "destination": str(dest), "sha256": _sha(dest),
            "IMPORTANT": "SUMO re-scans at STARTUP ONLY. Restart SUMO before expecting to see "
                         "this model base.",
            "reminder": "A plant using a NEW state variable needs a recompile AND explicit "
                        "state re-initialisation - state.xml is keyed by exact variable name."}


@_locked
def uninstall_process_unit(slug: str | pathlib.Path,
                           custom_root: str | pathlib.Path = "custom_units",
                           opt_in: bool = False) -> dict:
    """Remove exactly the files the install manifest lists. Never a tree, never a pattern."""
    if not opt_in:
        return {"uninstalled": False, "reason": "opt_in is required (this writes into %s)"
                                                % INSTALL_ROOT}
    slug_dir = _find_slug(slug, custom_root)
    if slug_dir is None:
        return {"uninstalled": False, "reason": "slug directory not found: %s" % slug}
    mpath = slug_dir / MANIFEST_NAME
    if not mpath.exists():
        return {"uninstalled": False, "reason": "no install manifest at %s" % mpath,
                "detail": ["Without a manifest this tool does not know what it wrote, and it "
                           "will not guess by deleting a directory by name."]}

    try:
        manifest = json.loads(mpath.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or not isinstance(manifest.get('files'), list):
            raise ValueError('manifest must contain a files list')
        if any(not isinstance(rec, dict) or not isinstance(rec.get('path'), str)
               or not isinstance(rec.get('sha256'), str) for rec in manifest['files']):
            raise ValueError('invalid manifest file record')
    except (OSError, ValueError, TypeError) as exc:
        return {'uninstalled': False, 'reason': 'invalid install manifest: ' + str(exc)}
    removed, kept, missing = [], [], []
    for rec in manifest.get("files", []):
        p = pathlib.Path(rec["path"])
        try:
            _assert_overlay(p)
        except InstallPathError:
            kept.append({"path": str(p), "why": "outside the overlay - refusing to delete"})
            continue
        if not p.exists():
            missing.append(str(p))
            continue
        # Only remove a file that is still the one we installed.
        if _sha(p) != rec.get("sha256"):
            kept.append({"path": str(p),
                         "why": "changed since install - someone else edited it, leaving it"})
            continue
        p.unlink()
        removed.append(str(p))

    dest = pathlib.Path(manifest.get("destination", ""))
    dir_removed = False
    if dest.exists():
        try:
            _assert_overlay(dest)
            if not any(dest.iterdir()):
                dest.rmdir()
                dir_removed = True
        except (InstallPathError, OSError):
            pass
    if not kept and (removed or missing):
        mpath.unlink()
    return {"uninstalled": bool(removed), "reason": "ok" if removed else "nothing removed",
            "removed": removed, "kept": kept, "already_missing": missing,
            "directory_removed": dir_removed,
            "IMPORTANT": "SUMO re-scans at STARTUP ONLY - a removed unit stays visible in a "
                         "running GUI until restart."}


def list_installed(category: str | None = None) -> dict:
    """What is currently installed in the overlay (read-only scan)."""
    root = OVERLAY_UNITS if category is None else OVERLAY_UNITS / category
    if not root.exists():
        return {"ok": True, "overlay": str(OVERLAY_UNITS), "units": [],
                "note": "the overlay slot exists but holds no units"}
    units = []
    for wb in sorted(root.rglob("*.xlsx")):
        if "Group Info" in wb.name or wb.name.startswith("~$"):
            continue
        units.append({"name": wb.stem, "path": str(wb),
                      "category": wb.parent.parent.name, "family": wb.parent.name})
    return {"ok": True, "overlay": str(OVERLAY_UNITS), "n_units": len(units), "units": units}


if __name__ == "__main__":                                   # pragma: no cover
    print(__doc__)
