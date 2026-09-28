"""SUMO installation discovery, shared by runtime, authoring and setup.

Explicit paths take precedence and are never silently replaced with another install.
The MCP process never prompts; the installation CLI owns interactive recovery.
"""
from __future__ import annotations

import os
from pathlib import Path


def normalize_install_dir(path: str | Path) -> Path:
    candidate = Path(str(path).strip().strip('"')).expanduser().resolve()
    if candidate.is_file():
        candidate = candidate.parent
    for root in (candidate, *candidate.parents):
        if (root / "Sumo24.exe").is_file() and (root / "sumoscheduler.dll").is_file():
            return root
    raise ValueError(
        f"{candidate} is not a SUMO24 installation. Select the folder containing "
        "Sumo24.exe and sumoscheduler.dll, or a Process code / My Process Code folder inside it."
    )


def resolve_install_dir(explicit: str | Path | None = None, *, required: bool = False) -> Path | None:
    selected = explicit or os.environ.get("SUMO_INSTALL_DIR")
    if selected:
        try:
            return normalize_install_dir(selected)
        except ValueError:
            if required:
                raise
            return None
    candidates: list[str | Path] = []
    if os.name == "nt":
        import winreg
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(hive, r"SOFTWARE\Dynamita\Sumo24\PATHS") as key:
                    candidates.append(winreg.QueryValueEx(key, "INST")[0])
            except OSError:
                pass
    candidates.extend((Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Dynamita" / "Sumo24",
                       Path("D:/SUMO24"), Path("C:/SUMO24")))
    for candidate in candidates:
        try:
            return normalize_install_dir(candidate)
        except ValueError:
            continue
    if required:
        raise ValueError("SUMO24 was not found. Supply --sumo-dir with your SUMO files directory.")
    return None


def installation_path(*parts: str) -> Path:
    """Resolve optional-feature defaults without loading native code at import time."""
    root = resolve_install_dir()
    # A missing path is deliberate: capability checks must not mistake cwd for an install.
    return (root or Path(os.environ.get("SUMO_INSTALL_DIR", "__SUMO24_NOT_CONFIGURED__"))) .joinpath(*parts)
