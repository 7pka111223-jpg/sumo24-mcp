"""
icon_emitter.py — Group HH, ticket 12 Phase C2: emit the unit's `.emf` icon.

Every shipped unit workbook's `Appearance` table names an `.emf` beside it. That file is a GUI
contract **no compile rung reads**, so a missing or malformed icon is invisible until someone
opens SUMO — which is exactly why it is emitted and verified here rather than left to chance.

Two paths, per ticket 14:

  1. **placeholder** (default) — a real EMF written through GDI+ `Metafile(..., EmfPlusDual)`.
     [MEASURED on this machine: 912-byte file, `EMR_HEADER` dword `1`, `' EMF'` signature at
     offset 40.] Requires `pywin32` (`System.Drawing` via .NET is not available; this uses the
     Windows GDI+ path through PowerShell, which is present on the target machine).
  2. **template copy** — copy a user-supplied `.emf`, behind an explicit opt-in flag.

Whichever path runs, the provenance stamp records which: `icon=placeholder` or
`icon=template-copy=<src>`. A placeholder must never be mistaken for a designed icon.
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess
import tempfile

EMF_SIGNATURE_OFFSET = 40
EMF_SIGNATURE = b" EMF"

_PS_TEMPLATE = r"""
Add-Type -AssemblyName System.Drawing
$path = '{path}'
try {{
  $bmp = New-Object System.Drawing.Bitmap 1,1
  $g   = [System.Drawing.Graphics]::FromImage($bmp)
  $hdc = $g.GetHdc()
  $mf  = New-Object System.Drawing.Imaging.Metafile($path, $hdc, [System.Drawing.Imaging.EmfType]::EmfPlusDual)
  $g.ReleaseHdc($hdc); $g.Dispose()
  $mg  = [System.Drawing.Graphics]::FromImage($mf)
  $mg.FillRectangle([System.Drawing.Brushes]::{fill}, 0, 0, {w}, {h})
  $mg.DrawRectangle([System.Drawing.Pens]::Black, 0, 0, {w1}, {h1})
  $font = New-Object System.Drawing.Font('Arial', 9)
  $mg.DrawString('{label}', $font, [System.Drawing.Brushes]::Black, 6, 6)
  $font.Dispose(); $mg.Dispose(); $mf.Dispose(); $bmp.Dispose()
  Write-Output 'OK'
}} catch {{ Write-Output ('FAIL: ' + $_.Exception.Message) }}
"""


def is_valid_emf(path: str | pathlib.Path) -> dict:
    """Structural check on the FILE, not on the writer's say-so."""
    p = pathlib.Path(path)
    if not p.exists():
        return {"valid": False, "reason": "file does not exist"}
    head = p.read_bytes()[:64]
    if len(head) < 44:
        return {"valid": False, "reason": f"too short ({p.stat().st_size} bytes)"}
    first_dword = int.from_bytes(head[0:4], "little")
    sig = head[EMF_SIGNATURE_OFFSET:EMF_SIGNATURE_OFFSET + 4]
    if first_dword != 1:
        return {"valid": False, "reason": f"first dword {first_dword} != 1 (EMR_HEADER)"}
    if sig != EMF_SIGNATURE:
        return {"valid": False, "reason": f"signature {sig!r} != {EMF_SIGNATURE!r}"}
    return {"valid": True, "bytes": p.stat().st_size}


def emit_placeholder(out_path: str | pathlib.Path, label: str = "",
                     width: int = 174, height: int = 90) -> dict:
    """Write a placeholder EMF. Returns a structured result; verifies the bytes afterwards."""
    out = pathlib.Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    script = _PS_TEMPLATE.format(
        path=str(out).replace("'", "''"), fill="LightSteelBlue",
        w=width, h=height, w1=width - 1, h1=height - 1,
        label=(label or out.stem)[:24].replace("'", "''"))
    with tempfile.NamedTemporaryFile("w", suffix=".ps1", delete=False, encoding="utf-8") as fh:
        fh.write(script)
        ps = fh.name
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                            "-File", ps],
                           capture_output=True, text=True, timeout=120)
        out_text = (r.stdout or "").strip()
    except subprocess.TimeoutExpired:
        return {"emitted": False, "reason": "GDI+ placeholder generation timed out"}
    finally:
        try:
            pathlib.Path(ps).unlink()
        except OSError:
            pass

    if not out_text.startswith("OK"):
        return {"emitted": False, "reason": f"GDI+ failed: {out_text[:160]}"}
    check = is_valid_emf(out)
    if not check["valid"]:
        return {"emitted": False, "reason": f"wrote a file that is not a valid EMF: {check['reason']}"}
    return {"emitted": True, "path": str(out), "bytes": check["bytes"],
            "provenance": "icon=placeholder"}


def emit_from_template(out_path: str | pathlib.Path, template: str | pathlib.Path,
                       opt_in: bool = False) -> dict:
    """Copy a user-supplied `.emf`. Requires an explicit opt-in (ticket 14)."""
    if not opt_in:
        return {"emitted": False, "reason": "template copy requires an explicit opt-in flag",
                "detail": ["pass opt_in=True to copy a user-supplied icon"]}
    src = pathlib.Path(template)
    chk = is_valid_emf(src)
    if not chk["valid"]:
        return {"emitted": False, "reason": f"template is not a valid EMF: {chk['reason']}"}
    out = pathlib.Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, out)
    return {"emitted": True, "path": str(out), "bytes": out.stat().st_size,
            "provenance": f"icon=template-copy={src}"}


if __name__ == "__main__":                                   # pragma: no cover
    import sys
    tgt = sys.argv[1] if len(sys.argv) > 1 else "placeholder.emf"
    print(emit_placeholder(tgt))
