"""
smoke_test_build_cleanup.py
───────────────────────────
Ticket 16 — build cleanup and rollback.

Simulates a build interrupted partway, then confirms the workspace returns
to a clean state via two mechanisms:

  A. clean_build()  — wipes the derived build/ + artifacts/ dirs (idempotent)
  B. snapshot → debris → revert  — pipeline.snapshot tar rollback (reused)

Debris is fabricated to match the real interrupted-build shapes measured on
disk (custom_units/hh_cstr_v1/): truncated SMT XML, srcdir full of .cpp/.obj,
object_script.model.sumo, smt_stdout/slc_stdout/smtlog.txt, a partial build
search root with a half-written unit workbook.

The install-tree target (D:\\SUMO24\\Dir\\My Process Code\\) is NOT touched —
AGENT-RULES forbids writing there; install-target rollback is design-only
(see the ticket-16 answer).

Run:
    python smoke_test_build_cleanup.py
"""
import pathlib
import shutil
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(_HERE))

from pipeline import snapshot as _sn
from sumoslang_author import clean_build, snapshot_build, revert_build

_PASS = "✅"
_FAIL = "❌"


def _ok(label: str, condition: bool, detail: str = "") -> bool:
    status = _PASS if condition else _FAIL
    print(f"  {status} {label}" + (f" — {detail}" if detail else ""))
    return condition


def _fabricate_debris(slug: pathlib.Path) -> None:
    """Create a realistic interrupted-build state under slug/."""
    # --- partial artifacts/ ---
    art = slug / "artifacts"
    art.mkdir(parents=True, exist_ok=True)
    (art / "hh_demo_v1.xml").write_text(
        '<?xml version="1.0"?><SumoPlant name="hh_demo_v1"', encoding="utf-8"
    )  # truncated mid-document
    (art / "smt_stdout.txt").write_text("line1\nline2\n", encoding="utf-8")
    (art / "slc_stdout.txt").write_text("[ERROR] unresolved symbol\n", encoding="utf-8")
    (art / "smtlog.txt").write_text(
        "2026-09-06 08:38:30 [INFO] Reading D:\\SUMO24\\.installed-cache\\compat.xlc\n",
        encoding="utf-8",
    )

    # srcdir/ from a failed compile: .cpp + .obj pairs, object_script, .h/.gch
    srcdir = art / "srcdir"
    srcdir.mkdir(parents=True, exist_ok=True)
    for i in range(1, 9):
        (srcdir / f"model_sumo_{i:04d}.cpp").write_text(f"// cpp {i}\n", encoding="utf-8")
        (srcdir / f"model_sumo_{i:04d}.obj").write_bytes(b"\x00" * 64)
    (srcdir / "model_sumo.cpp").write_text("// model_sumo.cpp\n", encoding="utf-8")
    (srcdir / "model_sumo.h").write_text("// header\n", encoding="utf-8")
    (srcdir / "model_moc.cpp").write_text("// moc\n", encoding="utf-8")
    (srcdir / "object_script.model.sumo").write_text("LIBS += -lsumocore\n", encoding="utf-8")
    (srcdir / "model_sumo.h.gch").write_bytes(b"\x00" * 4096)

    # a half-written DLL
    (art / "hh_demo_v1.dll").write_bytes(b"MZ\x90\x00" + b"\x00" * 256)

    # --- partial build/ search root ---
    bld = slug / "build"
    bld.mkdir(parents=True, exist_ok=True)
    for rel in (
        "Plant instances/hh_demo_v1.xlsx",
        "Plant classes/Plant.xlsx",
        "Process units/Custom/HH_DEMO_v1/HH_DEMO_v1.xlsx",
    ):
        p = bld / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"\x00" * 256)
    (bld / "smtlog.txt").write_text("partial run log\n", encoding="utf-8")


def _listing(slug: pathlib.Path) -> dict:
    """Return a map of relative path -> (kind, size) for everything under slug."""
    out = {}
    for p in sorted(slug.rglob("*")):
        if p.is_file():
            out[str(p.relative_to(slug)).replace("\\", "/")] = p.stat().st_size
    return out


def main() -> int:
    print("smoke_test_build_cleanup.py — ticket 16 cleanup & rollback")
    results: list[bool] = []

    with tempfile.TemporaryDirectory(prefix="hh_cleanup_") as tmp:
        slug = pathlib.Path(tmp) / "hh_demo_v1"
        slug.mkdir()
        (slug / "unit_spec.json").write_text(
            '{"name": "hh_demo_v1", "version": "v1", "routed_as": "A"}',
            encoding="utf-8",
        )

        # ── Scenario A: clean_build wipes a partial build, then converges ──
        print("\nScenario A — clean_build on an interrupted build:")
        _fabricate_debris(slug)
        res1 = clean_build(slug)
        ok_a = _ok("build+artifacts removed",
                   set(res1["removed"]) == {"build", "artifacts"},
                   f"removed={res1['removed']}")
        remaining = _listing(slug)
        ok_a &= _ok("only unit_spec.json remains",
                    set(remaining) == {"unit_spec.json"},
                    f"remaining={sorted(remaining)}")

        res2 = clean_build(slug)
        ok_a &= _ok("second clean_build is a no-op (idempotent)",
                    res2["removed"] == [] and _listing(slug) == {"unit_spec.json": len(
                        '{"name": "hh_demo_v1", "version": "v1", "routed_as": "A"}')},
                    f"removed={res2['removed']}")
        results.append(ok_a)

        # ── Scenario B: snapshot → debris → revert restores the clean state ──
        print("\nScenario B — snapshot/revert around a failed build:")
        snap1 = snapshot_build(slug, "pre_build")
        clean_listing = _listing(slug)
        _fabricate_debris(slug)
        n_debris = len(_listing(slug))
        ok_b = _ok(f"debris fabricated ({n_debris} files) for the interrupted build",
                   n_debris > len(clean_listing))

        restored = revert_build(slug, "pre_build")
        ok_b &= _ok("revert restored the pre-build snapshot",
                    _listing(slug) == clean_listing,
                    f"restored_from={pathlib.Path(restored).name}")
        ok_b &= _ok("no debris survives the revert",
                    not any("srcdir" in k or "artifacts" in k or "build/" in k
                            for k in _listing(slug)))
        results.append(ok_b)

        # ── Scenario C: retention prunes to KEEP=30 ──
        print("\nScenario C — snapshot retention (prune to KEEP=30):")
        for i in range(35):
            snapshot_build(slug, f"build_{i:02d}")
        snaps = _sn.list_snapshots(slug)
        ok_c = _ok(f"{len(snaps)} snapshots retained (≤ KEEP=30)", len(snaps) <= 30)
        results.append(ok_c)

    print()
    all_ok = all(results)
    print("RESULT:", "PASS" if all_ok else "FAIL")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())