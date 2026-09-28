"""
slc_runner.py — Group HH, ticket 12 Phase D2: rung 4, the `slcompiler.exe` wrapper.

`slcompiler.exe` turns the SMT's intermediate XML into a linked model DLL (it drives a bundled
MinGW g++). It is the third tool in this stack that reports success while failing.

THE RULES, each measured:

  * **The exit code is not evidence.** [MEASURED] `slcompiler` prints `[ERROR]` usage text and
    still **exits 0**. Success is the `Task: Link - Success` line in stdout, AND a DLL that
    exists, AND a DLL whose PE header says PE32+ x86-64. All three, or it failed.

  * **`-srcdir` must ALREADY EXIST.** [MEASURED this session] Passing a non-existent directory
    fails with `[ERROR]: Path not found: <dir>` and exit 127, producing no DLL. The wrapper
    creates it rather than letting a caller lose a run to it.

  * **A DLL on disk is not a working DLL.** The PE header is read and checked
    (`machine == 0x8664`); a 32-bit or truncated artefact is a failure, not a success.

  * **Every call has a timeout.** Linking is the slowest stage in the chain.

`verify_pe32plus()` is deliberately a separate public function: rung 5 and the end-to-end gate
need to check a DLL they did not build.
"""
from __future__ import annotations

import os
import pathlib
import subprocess

DEFAULT_SLC = pathlib.Path(r"D:\SUMO24\slcompiler.exe")
DEFAULT_BASE_PATH = pathlib.Path(r"D:\SUMO24")
DEFAULT_TIMEOUT = 1800

# [MEASURED 2026-09-07] slcompiler spawns MinGW g++ 5.2, whose driver cannot locate
# cc1plus/as or its own runtime DLLs unless its bin dir is on PATH. Machine and user
# PATH do not contain it, so every compile task exits 1 with EMPTY Output/Error logs
# and no "Task: Link - Success" line. Prepending <base_path>/build/mingw/bin makes
# the wrapper self-sufficient regardless of how the server process was launched.
MINGW_BIN_SUBPATH = pathlib.Path("build") / "mingw" / "bin"


def _linker_env(base_path: str | pathlib.Path) -> dict:
    env = dict(os.environ)
    mingw_bin = pathlib.Path(base_path) / MINGW_BIN_SUBPATH
    if mingw_bin.is_dir():
        env["PATH"] = str(mingw_bin) + os.pathsep + env.get("PATH", "")
    return env

LINK_SUCCESS = "Task: Link - Success"
IMAGE_FILE_MACHINE_AMD64 = 0x8664


def verify_pe32plus(dll_path: str | pathlib.Path) -> dict:
    """Read the PE header. A file existing is not the same as a loadable 64-bit DLL."""
    p = pathlib.Path(dll_path)
    if not p.exists():
        return {"ok": False, "reason": "file does not exist"}
    size = p.stat().st_size
    if size < 0x400:
        return {"ok": False, "reason": f"too small to be a PE image ({size} bytes)"}
    with p.open('rb') as stream:
        head = stream.read(0x400)
    if head[:2] != b"MZ":
        return {"ok": False, "reason": "missing MZ DOS signature"}
    pe_off = int.from_bytes(head[0x3c:0x40], 'little')
    if pe_off + 26 > size:
        return {"ok": False, "reason": "PE header offset is outside the image"}
    with p.open('rb') as stream:
        stream.seek(pe_off)
        pe_head = stream.read(26)
    if pe_head[:4] != b"PE\0\0":
        return {"ok": False, "reason": "missing PE signature"}
    machine = int.from_bytes(pe_head[4:6], "little")
    sections = int.from_bytes(pe_head[6:8], "little")
    if machine != IMAGE_FILE_MACHINE_AMD64:
        return {"ok": False, "reason": f"machine 0x{machine:04x} is not x86-64 (0x8664)",
                "bytes": size}
    if int.from_bytes(pe_head[24:26], 'little') != 0x20b:
        return {"ok": False, "reason": "optional header is not PE32+"}
    return {"ok": True, "bytes": size, "machine": "PE32+ x86-64", "sections": sections}


from compiler_lock import serialized


@serialized
def run_slcompiler(xml_path: str | pathlib.Path,
                   dll_out: str | pathlib.Path,
                   srcdir: str | pathlib.Path,
                   base_path: str | pathlib.Path = DEFAULT_BASE_PATH,
                   timeout: int = DEFAULT_TIMEOUT,
                   slc_exe: str | pathlib.Path = DEFAULT_SLC,
                   cwd: str | pathlib.Path | None = None) -> dict:
    """Compile the SMT XML to a DLL. Structured verdict; the return code is never the evidence."""
    xml = pathlib.Path(xml_path).resolve()
    dll = pathlib.Path(dll_out).resolve()
    src = pathlib.Path(srcdir).resolve()
    exe = pathlib.Path(slc_exe)
    if os.environ.get('SUMO_INSTALL_DIR'):
        from sumo_paths import resolve_install_dir
        install = resolve_install_dir(required=True)
        if exe == DEFAULT_SLC:
            exe = install / 'slcompiler.exe'
        if pathlib.Path(base_path) == DEFAULT_BASE_PATH:
            base_path = install

    if not exe.exists():
        return {"ok": False, "stage": "preflight", "reason": f"slcompiler not found at {exe}"}
    if not xml.exists():
        return {"ok": False, "stage": "preflight", "reason": f"XML not found: {xml}"}

    # MEASURED: a missing -srcdir fails with "[ERROR]: Path not found" and exit 127.
    src.mkdir(parents=True, exist_ok=True)
    dll.parent.mkdir(parents=True, exist_ok=True)
    if dll.exists():
        dll.unlink()

    args = [str(exe), str(xml), "-bp", str(base_path), "-srcdir", str(src), "-o", str(dll)]
    work = pathlib.Path(cwd).resolve() if cwd else dll.parent

    try:
        proc = subprocess.run(args, cwd=str(work), capture_output=True, text=True,
                              timeout=timeout, env=_linker_env(base_path))
        rc = proc.returncode
        stdout = (proc.stdout or "") + (proc.stderr or "")
        timed_out = False
    except subprocess.TimeoutExpired:
        rc, stdout, timed_out = None, "", True

    if timed_out:
        return {"ok": False, "stage": "link", "timed_out": True, "returncode": None,
                "reason": f"slcompiler exceeded its {timeout}s timeout", "command": args}

    errors = [ln.strip() for ln in stdout.splitlines() if "[ERROR]" in ln]
    linked = LINK_SUCCESS in stdout
    pe = verify_pe32plus(dll)

    ok = linked and pe["ok"] and not errors
    if ok:
        reason = "linked, and the DLL is a valid PE32+ x86-64 image"
    elif errors:
        reason = f"slcompiler reported {len(errors)} [ERROR] line(s)"
    elif not linked:
        reason = f"no {LINK_SUCCESS!r} line in stdout"
    else:
        reason = f"DLL rejected: {pe['reason']}"

    if ok:
        import build_provenance
        try:
            build_provenance.record_link(xml, dll)
        except (OSError, ValueError, KeyError) as exc:
            ok = False
            reason = "build provenance failed: " + str(exc)

    return {
        "ok": ok,
        "stage": "link",
        "reason": reason,
        "returncode": rc,
        "returncode_is_not_evidence": True,
        "link_success_line": linked,
        "errors": errors[:20],
        "dll": str(dll) if dll.exists() else None,
        "pe": pe,
        "srcdir": str(src),
        "command": args,
        "stdout_tail": stdout[-600:],
    }


if __name__ == "__main__":                                   # pragma: no cover
    print(__doc__)
