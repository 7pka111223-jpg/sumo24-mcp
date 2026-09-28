"""
smt_runner.py — Group HH, ticket 12 Phase D1: rung 3, the `SMT24.exe` wrapper.

`SMT24.exe` turns a plant instance workbook into the intermediate XML that `slcompiler.exe`
consumes. It is the first of the three tools in this stack that **report success while
failing**, so this wrapper exists mainly to refuse to believe it.

THE RULES, each from a measured failure — not one of them is defensive style:

  * **The exit code is not evidence.** [MEASURED] `SMT24.exe` returns **exit 0 on a reader
    error**. It also returns exit 0 under `-nosort` while emitting a dangling-reference
    `[ERROR]`. Success is judged on the LOG plus the ARTEFACT, never on the return value.

  * **`smtlog.txt` is written to the INVOCATION CWD, not `D:\\SUMO24`.** [MEASURED: a harness
    copy held 3,701 bytes of `[ERROR]` lines while `D:\\SUMO24\\smtlog.txt` was **0 bytes**.]
    A wrapper reading the install path finds an empty file, sees no errors, and reports success
    on a failed compile. This wrapper reads the CWD copy first and says which one it used.

  * **Every call has a timeout.** [MEASURED] A structurally invalid unit makes the SMT *hang*
    rather than error. Rung 1 must run before this rung so obviously-broken specs never get here.

  * **`-nosort` is BANNED unless explicitly requested as a diagnostic.** [MEASURED] It skips
    dependency sorting, so the emitted model's algebraic layer never evaluates: the DLL loads,
    integrates, and produces physically meaningless results with derived variables frozen at the
    `99999.9` sentinel. It converts a loud compile failure into a silent numerical one, which is
    strictly worse. Tickets 21-24 all carried it, and it cost the project a wrong diagnosis.

  * **The log is truncated per run.** Concurrent SMT runs share `smtlog.txt` and a name-keyed
    `.xlc` cache, so runs must be serialised; this wrapper clears the CWD log before invoking so
    the `[ERROR]` scan cannot pick up a previous run's failure.
"""
from __future__ import annotations

import os
import pathlib
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET

DEFAULT_SMT = pathlib.Path(r"D:\SUMO24\SMT24.exe")
INSTALL_LOG = pathlib.Path(r"D:\SUMO24\smtlog.txt")
DEFAULT_TIMEOUT = 600


def _read_log(cwd: pathlib.Path) -> tuple[str, str]:
    """Return (log_text, which_log). The CWD copy is authoritative; the install copy is fallback."""
    cwd_log = cwd / "smtlog.txt"
    if cwd_log.exists() and cwd_log.stat().st_size > 0:
        return cwd_log.read_text(encoding="utf-8", errors="replace"), str(cwd_log)
    if INSTALL_LOG.exists() and INSTALL_LOG.stat().st_size > 0:
        return INSTALL_LOG.read_text(encoding="utf-8", errors="replace"), str(INSTALL_LOG)
    return "", "(no smtlog found in CWD or install)"


# [MEASURED] The SMT writes level tags SPACE-PADDED to a fixed width: the installed build
# emits `[INFO    ]` and `[SMT               ]`, so an error line is `[ERROR   ]`, NOT
# `[ERROR]`. An earlier version of this scanner matched the literal substring "[ERROR]" and
# therefore matched NOTHING: rung 3's primary success signal was dead code and the verdict
# survived on `xml_ok` alone. Found by adversarial review; the map's SYSTEMIC TRAP table
# carried the same wrong literal.
_LEVEL_ERROR = re.compile(r"\[\s*(ERROR|FATAL|SEVERE)\s*\]", re.IGNORECASE)


def error_lines(log_text: str) -> list[str]:
    """Lines carrying an error-level tag, tolerant of the SMT's space padding."""
    return [ln.strip() for ln in log_text.splitlines() if _LEVEL_ERROR.search(ln)]


from compiler_lock import serialized


@serialized
def run_smt(instance_xlsx: str | pathlib.Path,
            out_xml: str | pathlib.Path,
            cwd: str | pathlib.Path | None = None,
            addpaths: list[str] | None = None,
            timeout: int = DEFAULT_TIMEOUT,
            smt_exe: str | pathlib.Path = DEFAULT_SMT,
            allow_nosort: bool = False,
            check_symbols: list[str] | None = None,
            extra_args: list[str] | None = None) -> dict:
    """Run the SMT. Returns a structured verdict; never raises on tool failure.

    `ok` is True only when ALL of these hold:
      - no `[ERROR]` line in the smtlog resolved against the invocation CWD, and
      - the output XML exists, is non-empty, and PARSES as XML, and
      - if `check_symbols` is given, none of them is REFERENCED-but-UNDECLARED.

    The process return code is reported for information and is never part of that decision.

    **Why `check_symbols` matters.** [MEASURED] A clean SMT run is NECESSARY BUT NOT SUFFICIENT:
    a bare-`Simple CSTR` reactive plant produces exit 0, ZERO `[ERROR]` lines and a valid
    1.78 MB XML that parses - and that XML still carries dangling `etaFLOC_Process`,
    `kLaGCO2_bub`, `SGO2_bub_sat` and `kLaGN2_bub`, which fail at link time. Rung 3 saying
    "clean" is a lie of omission unless the symbols are checked here, before a long link burns
    on an artefact that cannot succeed.
    """
    inst = pathlib.Path(instance_xlsx).resolve()
    out = pathlib.Path(out_xml).resolve()
    work = pathlib.Path(cwd).resolve() if cwd else out.parent
    exe = pathlib.Path(smt_exe)
    if os.environ.get('SUMO_INSTALL_DIR') and exe == DEFAULT_SMT:
        from sumo_paths import resolve_install_dir
        exe = resolve_install_dir(required=True) / 'SMT24.exe'

    if not exe.exists():
        return {"ok": False, "stage": "preflight", "reason": f"SMT not found at {exe}"}
    if not inst.exists():
        return {"ok": False, "stage": "preflight", "reason": f"instance not found: {inst}"}

    import build_provenance
    provenance_snapshot = build_provenance.begin_smt(inst, out, addpaths, exe)

    args = [str(exe), str(inst), str(out)]
    for p in (addpaths or []):
        args += ["-addpath", str(p)]
    extra = list(extra_args or [])
    if "-nosort" in extra and not allow_nosort:
        return {"ok": False, "stage": "preflight",
                "reason": "-nosort is banned outside diagnostics",
                "detail": ["It skips dependency sorting: the model compiles and integrates but "
                           "its algebraic layer never evaluates, leaving derived variables at "
                           "the 99999.9 sentinel and results physically meaningless.",
                           "Pass allow_nosort=True only to reproduce a known-bad build."]}
    args += extra

    work.mkdir(parents=True, exist_ok=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    # Clear the CWD log so a previous run's [ERROR] lines cannot be read as this run's.
    try:
        (work / "smtlog.txt").unlink()
    except OSError:
        pass
    if out.exists():
        out.unlink()

    try:
        proc = subprocess.run(args, cwd=str(work), capture_output=True, text=True,
                              timeout=timeout)
        rc, stdout, stderr = proc.returncode, proc.stdout or "", proc.stderr or ""
        timed_out = False
    except subprocess.TimeoutExpired:
        rc, stdout, stderr, timed_out = None, "", "", True

    log_text, which_log = _read_log(work)
    errs = error_lines(log_text)

    if timed_out:
        return {"ok": False, "stage": "run", "returncode": None, "timed_out": True,
                "reason": f"SMT exceeded its {timeout}s timeout",
                "detail": ["A structurally invalid unit makes the SMT hang rather than error. "
                           "Run rung 1 before rung 3."],
                "smtlog": which_log, "errors": errs}

    xml_ok, xml_detail = False, "not produced"
    if out.exists() and out.stat().st_size > 0:
        try:
            ET.parse(str(out))
            xml_ok, xml_detail = True, f"{out.stat().st_size} bytes, parses"
        except ET.ParseError as e:
            xml_detail = f"exists ({out.stat().st_size} bytes) but does NOT parse: {e}"

    dangling = None
    if xml_ok and check_symbols:
        dangling = dangling_symbols(out, check_symbols)

    ok = (not errs) and xml_ok and (dangling is None or dangling["ok"])
    if ok and not allow_nosort:
        try:
            build_provenance.record_smt(inst, out, provenance_snapshot)
        except (OSError, ValueError) as exc:
            return {"ok": False, "stage": "provenance", "reason": str(exc)}

    return {
        "ok": ok,
        "dangling": (dangling["dangling"] if dangling else None),
        "symbols_checked": bool(check_symbols),
        "stage": "run",
        "reason": ("clean: no [ERROR] lines, the XML parses"
                   + (", and no dangling symbols" if check_symbols else
                      " (SYMBOLS NOT CHECKED - a clean run can still carry dangling refs)")
                   if ok else
                   ("SMT reported [ERROR] lines" if errs else
                    (f"XML {xml_detail}" if not xml_ok else
                     f"XML is clean but carries dangling symbols: {dangling['dangling']}"))),
        "returncode": rc,
        "returncode_is_not_evidence": True,
        "smtlog": which_log,
        "errors": errs[:20],
        "n_errors": len(errs),
        "xml": str(out) if out.exists() else None,
        "xml_status": xml_detail,
        "command": args,
        "stdout_tail": stdout[-400:],
        "stderr_tail": stderr[-400:],
    }


def declared_variables(xml_path: str | pathlib.Path) -> set[str]:
    """`cname`s of every `<variable>` in the emitted XML — the measurement rungs 3/5 rely on."""
    names: set[str] = set()
    try:
        for _ev, el in ET.iterparse(str(xml_path), events=("end",)):
            if el.tag.endswith("variable"):
                cn = el.get("cname")
                if cn:
                    names.add(cn)
                el.clear()
    except (ET.ParseError, OSError):
        return set()
    return names


def dangling_symbols(xml_path: str | pathlib.Path, candidates: list[str]) -> dict:
    """For each candidate: is it REFERENCED in the XML text but never DECLARED?

    This is the measurement tickets 21-24 turned on, kept here so it is reusable rather than
    re-derived: a symbol that is referenced without a `<variable>` declaration will fail at
    `slcompiler` link time with an undefined-symbol error.
    """
    try:
        text = pathlib.Path(xml_path).read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return {"ok": False, "reason": str(e)}
    declared = declared_variables(xml_path)
    out = {}
    for sym in candidates:
        referenced = sym in text
        is_declared = any(d.endswith(sym) or d.endswith("__" + sym) for d in declared)
        out[sym] = {"referenced": referenced, "declared": is_declared}
    dangling = [s for s, v in out.items() if v["referenced"] and not v["declared"]]
    return {"ok": not dangling, "per_symbol": out, "dangling": dangling,
            "n_declared_total": len(declared)}


if __name__ == "__main__":                                   # pragma: no cover
    print(__doc__)
