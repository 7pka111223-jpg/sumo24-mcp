"""
sumo_gui.py  —  Group GG support module (SUMO24 MCP)

Drives the SUMO24 desktop GUI via Windows UI Automation (pywinauto).
This is the "GUI control" path — distinct from the DTT/Group FF "headless"
path which talks straight to the compiled model DLL.

Design notes
------------
* All UI selectors (window title regexes, palette item names, canvas
  coordinates, menu paths) are read from a sibling calibration JSON
  (default: sumo_gui_layout.json). The user fills in this file once for
  their SUMO24 install; nothing here hard-codes a SUMO version.
* pywinauto + Pillow are optional dependencies. If pywinauto isn't
  installed, every function returns {"ok": false, "error": "..."} so the
  server stays alive.
* All public functions return plain dicts; the server wraps the result
  into the project's JSON return envelope.

MVP operations
--------------
* launch_sumo_gui       — start the SUMO24 process and attach
* gui_add_unit_to_canvas — click a palette item, drop it at (x, y)
* gui_save_sumo          — Ctrl+S, type a path, hit Save
* gui_screenshot         — capture the SUMO main window to a PNG

Extended operations (v2 — coordinate-based, robust to owner-drawn palettes)
---------------------------------------------------------------------------
SUMO24's palette uses owner-drawn image icons that are NOT exposed by name
in the UIA tree, so `gui_add_unit_to_canvas` (which does a title lookup)
fails on this UI. The functions below avoid the UIA tree entirely and
drive the canvas with calibrated client-area pixel coordinates.

* gui_focus_sumo                 — bring the SUMO window forward
* gui_get_window_rect            — current window bounds
* gui_click_at                   — left/right/double-click at canvas (x, y)
* gui_drag_from_to               — drag from (x1, y1) to (x2, y2)
* gui_send_keys                  — send a pywinauto key sequence
* gui_type_text                  — type literal text (clipboard fast path)
* gui_calibrate_palette_item     — record palette icon (x, y) into layout
* gui_drop_unit_at               — drag from calibrated palette icon to canvas
* gui_list_palette_items         — return current palette calibration
* gui_open_unit_properties       — double-click a canvas unit to open dialog
* gui_set_param_in_dialog        — fill a parameter row in the open dialog
* gui_close_dialog               — press OK (Enter) or Cancel (Escape)
* gui_connect_units              — wire outlet of unit A to inlet of unit B
* gui_switch_tab                 — switch the SUMO ribbon tab by name
"""

from __future__ import annotations
import datetime as _dt
import json
import os
import subprocess
import time
from typing import Any, Dict, Optional, Tuple

# --- Optional dependencies -------------------------------------------------
try:
    from pywinauto import Application, Desktop  # type: ignore
    from pywinauto.keyboard import send_keys     # type: ignore
    PYWINAUTO_AVAILABLE = True
    _PYWINAUTO_IMPORT_ERROR: Optional[str] = None
except Exception as _e_pwa:                      # pragma: no cover
    Application = None  # type: ignore
    Desktop = None      # type: ignore
    send_keys = None    # type: ignore
    PYWINAUTO_AVAILABLE = False
    _PYWINAUTO_IMPORT_ERROR = repr(_e_pwa)

try:
    from PIL import ImageGrab, Image as _PILImage  # type: ignore
    PIL_AVAILABLE = True
except Exception:                                # pragma: no cover
    ImageGrab = None  # type: ignore
    _PILImage = None  # type: ignore
    PIL_AVAILABLE = False

try:
    import cv2 as _cv2  # type: ignore
    import numpy as _np  # type: ignore
    CV2_AVAILABLE = True
    _CV2_IMPORT_ERROR: Optional[str] = None
except Exception as _e_cv2:                      # pragma: no cover
    _cv2 = None  # type: ignore
    _np = None  # type: ignore
    CV2_AVAILABLE = False
    _CV2_IMPORT_ERROR = repr(_e_cv2)

# --- Defaults --------------------------------------------------------------
_DEFAULT_LAYOUT_NAME = "sumo_gui_layout.json"

# Skeleton the user can edit / replace. Any field missing here is treated
# as "not calibrated yet" and produces a clear error message at call time.
_LAYOUT_SKELETON: Dict[str, Any] = {
    "_comment": (
        "Calibration file for Group GG (SUMO24 GUI control). "
        "Fill in the fields for your local SUMO24 install. "
        "Coordinates are client-area pixels relative to the SUMO main "
        "window. Use gui_screenshot to capture the canvas and read off "
        "coordinates with any image editor."
    ),
    "executable": "C:/Program Files/Dynamita/SUMO24/SUMO24.exe",
    "window_title_regex": "(?i)sumo.*",
    "launch_timeout_s": 60,
    "post_launch_wait_s": 4,
    "palette": {
        # Map "unit_type" → palette item name (UI Automation .Name property)
        # or a {x: ..., y: ...} click point inside the palette panel.
        "AerationTank":        {"name": "Aeration Tank"},
        "PrimaryClarifier":    {"name": "Primary Clarifier"},
        "SecondaryClarifier":  {"name": "Secondary Clarifier"},
        "Influent":            {"name": "Influent"},
        "Effluent":            {"name": "Effluent"},
        "Mixer":               {"name": "Mixer"},
        "Splitter":            {"name": "Splitter"},
        "Digester":            {"name": "Digester"}
    },
    "canvas": {
        # Default drop point if the caller doesn't provide one.
        "default_drop": {"x": 600, "y": 400}
    },
    "save_dialog": {
        # SaveAs dialog text-field selector. "auto_keys=True" means we
        # type the path with send_keys after pressing Ctrl+S.
        "auto_keys": True,
        "filename_field_name": "File name:",
        "save_button_name": "Save"
    }
}


# ---------------------------------------------------------------------------
# Calibration loader / writer
# ---------------------------------------------------------------------------
def layout_path(layout_file: Optional[str] = None) -> str:
    if layout_file:
        return layout_file
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, _DEFAULT_LAYOUT_NAME)


def load_layout(layout_file: Optional[str] = None) -> Dict[str, Any]:
    p = layout_path(layout_file)
    if not os.path.isfile(p):
        if layout_file:
            return {"ok": False, "error": f"layout file not found: {p}"}
        import copy
        from sumo_paths import installation_path
        data = copy.deepcopy(_LAYOUT_SKELETON)
        data["executable"] = str(installation_path("Sumo24.exe"))
        return {"ok": True, "layout": data, "path": p, "source": "installation defaults"}
    try:
        with open(p, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as e:
        return {"ok": False, "error": f"could not parse layout: {e!r}"}
    return {"ok": True, "layout": data, "path": p}


def write_layout_skeleton(layout_file: Optional[str] = None,
                          overwrite: bool = False) -> Dict[str, Any]:
    p = layout_path(layout_file)
    if os.path.isfile(p) and not overwrite:
        return {"ok": False,
                "error": f"layout already exists at {p}; "
                         f"pass overwrite=True to replace"}
    try:
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(_LAYOUT_SKELETON, fh, indent=2)
    except OSError as e:
        return {"ok": False, "error": f"write failed: {e!r}"}
    return {"ok": True, "path": p, "wrote_skeleton": True}


# ---------------------------------------------------------------------------
# Dependency guard
# ---------------------------------------------------------------------------
def deps_check() -> Dict[str, Any]:
    return {"pywinauto": PYWINAUTO_AVAILABLE,
            "pywinauto_import_error": _PYWINAUTO_IMPORT_ERROR,
            "PIL": PIL_AVAILABLE}


def _require_pwa() -> Optional[Dict[str, Any]]:
    if not PYWINAUTO_AVAILABLE:
        return {"ok": False,
                "error": "pywinauto not installed",
                "detail": _PYWINAUTO_IMPORT_ERROR,
                "next_step": "pip install pywinauto pillow"}
    return None


# ---------------------------------------------------------------------------
# Window / process helpers (pywinauto backed)
# ---------------------------------------------------------------------------
def _connect_main_window(layout: Dict[str, Any]):
    """Return the top-level SUMO window via pywinauto, or raise."""
    title_re = layout.get("window_title_regex", "SUMO ?24.*")
    # Try existing instance first
    try:
        app = Application(backend="uia").connect(title_re=title_re, timeout=2)
        win = app.window(title_re=title_re)
        rect = win.rectangle()
        if rect.width() < 600 or rect.height() < 400:
            raise RuntimeError("SUMO splash visible; main window is not ready")
        return app, win
    except Exception:
        pass
    raise RuntimeError(f"No SUMO24 window matching /{title_re}/")


def launch_sumo_gui(layout_file: Optional[str] = None,
                    extra_args: Optional[list] = None) -> Dict[str, Any]:
    g = _require_pwa()
    if g:
        return g
    lay = load_layout(layout_file)
    if not lay.get("ok"):
        return lay
    layout = lay["layout"]
    exe = layout.get("executable")
    if os.environ.get("SUMO_INSTALL_DIR") and not layout_file:
        from sumo_paths import installation_path
        exe = str(installation_path("Sumo24.exe"))
    if not exe or not os.path.isfile(exe):
        return {"ok": False,
                "error": f"executable not found at {exe!r}; "
                         f"edit {lay['path']} 'executable' field."}
    # If already running, just attach.
    try:
        _, win = _connect_main_window(layout)
        rect = win.rectangle()
        return {"ok": True, "already_running": True,
                "window": {"title": win.window_text(),
                            "left": rect.left, "top": rect.top,
                            "right": rect.right, "bottom": rect.bottom}}
    except Exception:
        pass
    args = [exe] + (extra_args or [])
    try:
        subprocess.Popen(args, close_fds=True)
    except OSError as e:
        return {"ok": False, "error": f"launch failed: {e!r}"}
    timeout = float(layout.get("launch_timeout_s", 60))
    poll_until = time.time() + timeout
    last_err = None
    while time.time() < poll_until:
        try:
            _, win = _connect_main_window(layout)
            time.sleep(float(layout.get("post_launch_wait_s", 4)))
            rect = win.rectangle()
            return {"ok": True, "already_running": False,
                    "window": {"title": win.window_text(),
                                "left": rect.left, "top": rect.top,
                                "right": rect.right, "bottom": rect.bottom}}
        except Exception as e:
            last_err = repr(e)
            time.sleep(1.0)
    return {"ok": False,
            "error": f"SUMO24 launched but no window appeared within "
                     f"{timeout}s; last error: {last_err}"}


# ---------------------------------------------------------------------------
# Add unit to canvas
# ---------------------------------------------------------------------------
def gui_add_unit_to_canvas(unit_type: str,
                           x: Optional[int] = None,
                           y: Optional[int] = None,
                           layout_file: Optional[str] = None
                           ) -> Dict[str, Any]:
    g = _require_pwa()
    if g:
        return g
    lay = load_layout(layout_file)
    if not lay.get("ok"):
        return lay
    layout = lay["layout"]
    palette = layout.get("palette", {})
    if unit_type not in palette:
        return {"ok": False,
                "error": f"unit_type {unit_type!r} not mapped in "
                         f"layout.palette; known types: "
                         f"{sorted(palette.keys())}"}
    spec = palette[unit_type]
    canvas = layout.get("canvas", {})
    drop = canvas.get("default_drop", {"x": 600, "y": 400})
    if x is None: x = drop.get("x", 600)
    if y is None: y = drop.get("y", 400)
    try:
        _, win = _connect_main_window(layout)
    except RuntimeError as e:
        return {"ok": False, "error": str(e),
                "next_step": "Call launch_sumo_gui first."}
    win.set_focus()
    # Resolve the palette item: either by UIA name or by direct coordinates.
    try:
        if "name" in spec:
            try:
                item = win.child_window(title=spec["name"], control_type="Button")
                if not item.exists():
                    item = win.child_window(title=spec["name"])
                rect = item.rectangle()
                src_x = (rect.left + rect.right) // 2
                src_y = (rect.top + rect.bottom) // 2
            except Exception as e:
                return {"ok": False,
                        "error": f"palette item {spec['name']!r} not found "
                                 f"in UI tree: {e!r}"}
        elif "x" in spec and "y" in spec:
            wrect = win.rectangle()
            src_x = wrect.left + int(spec["x"])
            src_y = wrect.top + int(spec["y"])
        else:
            return {"ok": False,
                    "error": f"palette entry for {unit_type!r} needs "
                             f"either 'name' or 'x'+'y'"}
        # Drop target is client-area relative
        wrect = win.rectangle()
        dst_x = wrect.left + int(x)
        dst_y = wrect.top + int(y)
        try:
            win.drag_mouse_input((dst_x, dst_y), (src_x, src_y))
        except Exception:
            # Fallback: separate click + click sequence (some SUMO builds
            # don't accept a single drag — they expect "select tool, then
            # click on canvas").
            from pywinauto.mouse import click as _mclick  # type: ignore
            _mclick(coords=(src_x, src_y))
            time.sleep(0.2)
            _mclick(coords=(dst_x, dst_y))
        return {"ok": True,
                "unit_type": unit_type,
                "source_xy": [src_x, src_y],
                "drop_xy": [dst_x, dst_y],
                "note": "Canvas state is in the GUI; persist with gui_save_sumo."}
    except Exception as e:
        return {"ok": False, "error": f"add-unit failed: {e!r}"}


# ---------------------------------------------------------------------------
# Save current GUI project as .sumo
# ---------------------------------------------------------------------------
def gui_save_sumo(target_path: str,
                  layout_file: Optional[str] = None) -> Dict[str, Any]:
    g = _require_pwa()
    if g:
        return g
    lay = load_layout(layout_file)
    if not lay.get("ok"):
        return lay
    layout = lay["layout"]
    sd = layout.get("save_dialog", {})
    try:
        _, win = _connect_main_window(layout)
    except RuntimeError as e:
        return {"ok": False, "error": str(e),
                "next_step": "Call launch_sumo_gui first."}
    win.set_focus()
    # Issue Ctrl+S (most apps treat this as Save / Save-As when nothing was
    # saved previously). If you want unconditional Save-As, customise
    # 'shortcut' in layout.json (e.g. "^+s" for Ctrl+Shift+S).
    shortcut = sd.get("shortcut", "^s")
    try:
        send_keys(shortcut)
    except Exception as e:
        return {"ok": False, "error": f"shortcut send failed: {e!r}"}
    time.sleep(1.0)
    if not sd.get("auto_keys", True):
        return {"ok": True, "dispatched": "Ctrl+S",
                "note": "auto_keys disabled in layout; complete the Save "
                        "dialog manually."}
    # Fill in the file-name field and hit Save.
    # We type the path then press Alt+S — this works regardless of focus
    # because the OS shell File-Save dialog is a system control.
    target_path = os.path.abspath(target_path)
    try:
        # SHIFT+TAB / explicit field click would be ideal; in practice the
        # File-Save dialog opens with the filename field focused.
        send_keys("^a")           # select-all anything pre-filled
        time.sleep(0.1)
        send_keys(target_path.replace(" ", "{SPACE}"), with_spaces=False)
        time.sleep(0.2)
        send_keys("{ENTER}")
    except Exception as e:
        return {"ok": False, "error": f"dialog input failed: {e!r}"}
    time.sleep(1.0)
    saved = os.path.isfile(target_path)
    return {"ok": saved,
            "target_path": target_path,
            "file_exists_after_save": saved,
            "note": "If saved is false, the dialog may still be open. "
                    "Use gui_screenshot to inspect."}


# ---------------------------------------------------------------------------
# Screenshot the SUMO main window
# ---------------------------------------------------------------------------
def gui_screenshot(output_dir: str,
                   layout_file: Optional[str] = None
                   ) -> Dict[str, Any]:
    g = _require_pwa()
    if g:
        return g
    if not PIL_AVAILABLE:
        return {"ok": False,
                "error": "Pillow (PIL) not installed",
                "next_step": "pip install pillow"}
    lay = load_layout(layout_file)
    if not lay.get("ok"):
        return lay
    layout = lay["layout"]
    try:
        _, win = _connect_main_window(layout)
    except RuntimeError as e:
        return {"ok": False, "error": str(e),
                "next_step": "Call launch_sumo_gui first."}
    rect = win.rectangle()
    bbox = (rect.left, rect.top, rect.right, rect.bottom)
    try:
        img = ImageGrab.grab(bbox=bbox, all_screens=True)
    except Exception as e:
        return {"ok": False, "error": f"capture failed: {e!r}"}
    os.makedirs(output_dir, exist_ok=True)
    ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out = os.path.join(output_dir, f"sumo_gui_{ts}.png")
    try:
        img.save(out)
    except OSError as e:
        return {"ok": False, "error": f"save failed: {e!r}"}
    return {"ok": True, "path": out, "bbox": list(bbox),
            "size_bytes": os.path.getsize(out)}


# ═══════════════════════════════════════════════════════════════════════════
# v2 — coordinate-based canvas control
#
# These tools talk to the SUMO main window via raw pywinauto mouse / keyboard
# helpers (pywinauto.mouse, pywinauto.keyboard.send_keys), using client-area
# pixel coordinates that the caller supplies or that the layout file stores.
# They DELIBERATELY avoid pywinauto's UIA element lookup — SUMO24's process
# palette is owner-drawn and its icons are not exposed as named UIA children,
# which makes the title-based path in gui_add_unit_to_canvas unreliable.
# ═══════════════════════════════════════════════════════════════════════════

def _win_and_rect(layout: Dict[str, Any]):
    """Helper — return (win, rect) for the SUMO window, or raise RuntimeError."""
    _, win = _connect_main_window(layout)
    return win, win.rectangle()


def _to_screen(rect, x: int, y: int) -> Tuple[int, int]:
    """Translate (x, y) given in client coords to absolute screen coords."""
    return rect.left + int(x), rect.top + int(y)


def _save_layout(layout: Dict[str, Any], path: str) -> Dict[str, Any]:
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(layout, fh, indent=2)
    except OSError as e:
        return {"ok": False, "error": f"write failed: {e!r}"}
    return {"ok": True, "path": path}


# ---------------------------------------------------------------------------
# Window helpers
# ---------------------------------------------------------------------------
def gui_focus_sumo(layout_file: Optional[str] = None) -> Dict[str, Any]:
    """Bring the SUMO window to the foreground and return its rect."""
    g = _require_pwa()
    if g:
        return g
    lay = load_layout(layout_file)
    if not lay.get("ok"):
        return lay
    try:
        win, rect = _win_and_rect(lay["layout"])
    except RuntimeError as e:
        return {"ok": False, "error": str(e),
                "next_step": "Call launch_sumo_gui first."}
    try:
        win.set_focus()
    except Exception as e:
        return {"ok": False, "error": f"set_focus failed: {e!r}"}
    return {"ok": True,
            "window": {"title": win.window_text(),
                       "left": rect.left, "top": rect.top,
                       "right": rect.right, "bottom": rect.bottom}}


def gui_get_window_rect(layout_file: Optional[str] = None) -> Dict[str, Any]:
    """Return the current SUMO main-window bounding box (screen coords)."""
    g = _require_pwa()
    if g:
        return g
    lay = load_layout(layout_file)
    if not lay.get("ok"):
        return lay
    try:
        win, rect = _win_and_rect(lay["layout"])
    except RuntimeError as e:
        return {"ok": False, "error": str(e),
                "next_step": "Call launch_sumo_gui first."}
    return {"ok": True,
            "title": win.window_text(),
            "left": rect.left, "top": rect.top,
            "right": rect.right, "bottom": rect.bottom,
            "width": rect.right - rect.left,
            "height": rect.bottom - rect.top}


# ---------------------------------------------------------------------------
# Generic primitives — click / drag / keys
# ---------------------------------------------------------------------------
def gui_click_at(x: int, y: int,
                 button: str = "left",
                 clicks: int = 1,
                 modifiers: Optional[str] = None,
                 layout_file: Optional[str] = None) -> Dict[str, Any]:
    """Click at SUMO-client (x, y).
    button ∈ {"left", "right", "middle"}; clicks ∈ {1, 2}.
    modifiers is a pywinauto send_keys held-key string e.g. "+^" (Shift+Ctrl).
    """
    g = _require_pwa()
    if g:
        return g
    if button not in ("left", "right", "middle"):
        return {"ok": False, "error": f"button must be left/right/middle, got {button!r}"}
    if clicks not in (1, 2):
        return {"ok": False, "error": f"clicks must be 1 or 2, got {clicks}"}
    lay = load_layout(layout_file)
    if not lay.get("ok"):
        return lay
    try:
        win, rect = _win_and_rect(lay["layout"])
    except RuntimeError as e:
        return {"ok": False, "error": str(e),
                "next_step": "Call launch_sumo_gui first."}
    win.set_focus()
    sx, sy = _to_screen(rect, x, y)
    try:
        from pywinauto.mouse import click as _mc, double_click as _mdc, right_click as _mrc  # type: ignore
        if modifiers:
            send_keys("{" + modifiers + " down}")
        if button == "left":
            if clicks == 2:
                _mdc(coords=(sx, sy))
            else:
                _mc(coords=(sx, sy))
        elif button == "right":
            _mrc(coords=(sx, sy))
        else:  # middle
            from pywinauto.mouse import click as _mc2  # type: ignore
            _mc2(button="middle", coords=(sx, sy))
        if modifiers:
            send_keys("{" + modifiers + " up}")
    except Exception as e:
        return {"ok": False, "error": f"click failed: {e!r}"}
    return {"ok": True, "client_xy": [int(x), int(y)],
            "screen_xy": [sx, sy], "button": button, "clicks": clicks}


def gui_drag_from_to(x1: int, y1: int, x2: int, y2: int,
                     button: str = "left",
                     duration_s: float = 0.4,
                     layout_file: Optional[str] = None) -> Dict[str, Any]:
    """Drag from SUMO-client (x1, y1) to (x2, y2)."""
    g = _require_pwa()
    if g:
        return g
    lay = load_layout(layout_file)
    if not lay.get("ok"):
        return lay
    try:
        win, rect = _win_and_rect(lay["layout"])
    except RuntimeError as e:
        return {"ok": False, "error": str(e),
                "next_step": "Call launch_sumo_gui first."}
    win.set_focus()
    sx1, sy1 = _to_screen(rect, x1, y1)
    sx2, sy2 = _to_screen(rect, x2, y2)
    try:
        from pywinauto.mouse import press as _mpress, release as _mrelease, move as _mmove  # type: ignore
        _mpress(button=button, coords=(sx1, sy1))
        # Linear interpolation so SUMO sees a real drag, not a teleport.
        steps = max(8, int(duration_s * 60))
        for i in range(1, steps + 1):
            ix = int(sx1 + (sx2 - sx1) * i / steps)
            iy = int(sy1 + (sy2 - sy1) * i / steps)
            _mmove(coords=(ix, iy))
            time.sleep(duration_s / steps)
        _mrelease(button=button, coords=(sx2, sy2))
    except Exception as e:
        return {"ok": False, "error": f"drag failed: {e!r}"}
    return {"ok": True,
            "from_client": [int(x1), int(y1)], "to_client": [int(x2), int(y2)],
            "from_screen": [sx1, sy1], "to_screen": [sx2, sy2]}


def gui_send_keys(keys: str,
                  pause_s: float = 0.05,
                  layout_file: Optional[str] = None) -> Dict[str, Any]:
    """Send a pywinauto key sequence to the focused SUMO window.
    Examples:  "^s" (Ctrl+S), "{ENTER}", "{TAB 3}", "Hello{SPACE}World".
    """
    g = _require_pwa()
    if g:
        return g
    lay = load_layout(layout_file)
    if not lay.get("ok"):
        return lay
    try:
        win, _ = _win_and_rect(lay["layout"])
    except RuntimeError as e:
        return {"ok": False, "error": str(e),
                "next_step": "Call launch_sumo_gui first."}
    win.set_focus()
    try:
        send_keys(keys, pause=float(pause_s))
    except Exception as e:
        return {"ok": False, "error": f"send_keys failed: {e!r}"}
    return {"ok": True, "keys": keys}


def gui_type_text(text: str,
                  press_enter: bool = False,
                  layout_file: Optional[str] = None) -> Dict[str, Any]:
    """Type literal text into the focused SUMO field. Spaces and special
    chars (which send_keys treats as escape sequences) are handled."""
    g = _require_pwa()
    if g:
        return g
    lay = load_layout(layout_file)
    if not lay.get("ok"):
        return lay
    try:
        win, _ = _win_and_rect(lay["layout"])
    except RuntimeError as e:
        return {"ok": False, "error": str(e),
                "next_step": "Call launch_sumo_gui first."}
    win.set_focus()
    try:
        # send_keys with with_spaces=True passes spaces through literally.
        send_keys(text, with_spaces=True, with_tabs=True, with_newlines=False)
        if press_enter:
            send_keys("{ENTER}")
    except Exception as e:
        return {"ok": False, "error": f"type failed: {e!r}"}
    return {"ok": True, "typed_len": len(text), "enter": bool(press_enter)}


# ---------------------------------------------------------------------------
# Palette calibration & coord-based unit drop
# ---------------------------------------------------------------------------
def gui_calibrate_palette_item(unit_type: str,
                               x: int, y: int,
                               display_name: Optional[str] = None,
                               layout_file: Optional[str] = None
                               ) -> Dict[str, Any]:
    """Record the palette icon position for `unit_type` in the layout file.

    The pair (x, y) is the click point IN SUMO-CLIENT-AREA PIXELS — i.e. the
    same coordinate system gui_click_at and gui_drop_unit_at use. Take a
    gui_screenshot first, read the icon centre with any image viewer, then
    pass the values here. This persists into sumo_gui_layout.json.
    """
    g = _require_pwa()
    if g:
        return g
    lay = load_layout(layout_file)
    if not lay.get("ok"):
        return lay
    layout = lay["layout"]
    palette = layout.setdefault("palette", {})
    entry = palette.get(unit_type, {})
    entry["x"] = int(x)
    entry["y"] = int(y)
    if display_name:
        entry["name"] = str(display_name)
    palette[unit_type] = entry
    saved = _save_layout(layout, lay["path"])
    if not saved.get("ok"):
        return saved
    return {"ok": True,
            "unit_type": unit_type,
            "client_xy": [int(x), int(y)],
            "layout_file": lay["path"],
            "palette_entry": entry}


def gui_list_palette_items(layout_file: Optional[str] = None) -> Dict[str, Any]:
    """Return the current palette calibration table."""
    lay = load_layout(layout_file)
    if not lay.get("ok"):
        return lay
    palette = lay["layout"].get("palette", {})
    calibrated = [k for k, v in palette.items() if "x" in v and "y" in v]
    uncalibrated = [k for k in palette.keys() if k not in calibrated]
    return {"ok": True,
            "palette": palette,
            "calibrated": sorted(calibrated),
            "uncalibrated": sorted(uncalibrated),
            "layout_file": lay["path"]}


def gui_drop_unit_at(unit_type: str,
                     x: int, y: int,
                     layout_file: Optional[str] = None,
                     duration_s: float = 0.5) -> Dict[str, Any]:
    """Drag the calibrated palette icon for `unit_type` onto the canvas at
    (x, y). Both source and destination are in SUMO-client-area pixels.

    Pre-req: gui_calibrate_palette_item must have recorded an (x, y) for the
    unit_type — UIA name lookup is not attempted here (it doesn't work for
    SUMO's owner-drawn icons).
    """
    g = _require_pwa()
    if g:
        return g
    lay = load_layout(layout_file)
    if not lay.get("ok"):
        return lay
    layout = lay["layout"]
    palette = layout.get("palette", {})
    spec = palette.get(unit_type)
    if not spec:
        return {"ok": False,
                "error": f"unit_type {unit_type!r} not in layout.palette",
                "next_step": "Call gui_calibrate_palette_item first."}
    if "x" not in spec or "y" not in spec:
        return {"ok": False,
                "error": f"palette entry for {unit_type!r} has no (x, y)",
                "next_step": "Call gui_calibrate_palette_item to record one."}
    src_x, src_y = int(spec["x"]), int(spec["y"])
    return gui_drag_from_to(src_x, src_y, int(x), int(y),
                            duration_s=duration_s,
                            layout_file=layout_file)


# ---------------------------------------------------------------------------
# Unit properties dialog
# ---------------------------------------------------------------------------
def gui_open_unit_properties(x: int, y: int,
                             wait_s: float = 1.0,
                             layout_file: Optional[str] = None) -> Dict[str, Any]:
    """Double-click a canvas unit at (x, y) to open its properties dialog.
    Returns the title of any top-level window that appeared, if detectable.
    """
    r = gui_click_at(x, y, button="left", clicks=2, layout_file=layout_file)
    if not r.get("ok"):
        return r
    time.sleep(max(0.1, float(wait_s)))
    # Best-effort: enumerate visible top-level windows and report new ones.
    new_titles = []
    try:
        for w in Desktop(backend="uia").windows():
            try:
                t = w.window_text()
                if t and t not in ("Program Manager",):
                    new_titles.append(t)
            except Exception:
                pass
    except Exception:
        pass
    return {"ok": True,
            "double_clicked_xy": [int(x), int(y)],
            "top_level_windows": new_titles[:25]}


def gui_set_param_in_dialog(label: str, value: str,
                            press_enter_after: bool = False,
                            dialog_title_regex: Optional[str] = None,
                            layout_file: Optional[str] = None) -> Dict[str, Any]:
    """In the currently-open SUMO dialog, find the editable field next to a
    label (e.g. "Volume", "Fill ratio") and set it to `value`.

    Strategy:
      1. Locate the dialog window (top-level, matches dialog_title_regex if
         supplied; otherwise uses the foreground window).
      2. Find a Text/Static child whose name contains `label`.
      3. Find the nearest Edit/Spinner sibling — click it, select-all, type.
    """
    g = _require_pwa()
    if g:
        return g
    try:
        # Pick the dialog — prefer the regex if given, otherwise foreground.
        if dialog_title_regex:
            from pywinauto import Application as _App  # type: ignore
            app = _App(backend="uia").connect(title_re=dialog_title_regex, timeout=3)
            dlg = app.window(title_re=dialog_title_regex)
        else:
            # The dialog should be the foreground window after a double-click.
            from pywinauto import Desktop as _Desk  # type: ignore
            dlg = None
            for w in _Desk(backend="uia").windows(active_only=True):
                dlg = w
                break
            if dlg is None:
                return {"ok": False,
                        "error": "no foreground dialog detected; "
                                 "pass dialog_title_regex"}
        dlg.set_focus()
    except Exception as e:
        return {"ok": False, "error": f"dialog not found: {e!r}"}
    # Find the label, then the nearest editable sibling.
    try:
        labels = dlg.descendants(control_type="Text") + \
                 dlg.descendants(control_type="Group")
        target = None
        for el in labels:
            try:
                if label.lower() in (el.window_text() or "").lower():
                    target = el
                    break
            except Exception:
                continue
        if target is None:
            return {"ok": False,
                    "error": f"label {label!r} not found in dialog"}
        lr = target.rectangle()
        # Find the closest Edit control to the right of (and on the same
        # row as) the label.
        edits = dlg.descendants(control_type="Edit")
        best = None
        best_dx = 10**9
        for e in edits:
            try:
                er = e.rectangle()
                # Same row (vertical overlap) and to the right.
                if er.top <= lr.bottom and er.bottom >= lr.top \
                        and er.left >= lr.left:
                    dx = er.left - lr.right
                    if 0 <= dx < best_dx:
                        best, best_dx = e, dx
            except Exception:
                continue
        if best is None:
            return {"ok": False,
                    "error": f"no Edit control found to the right of "
                             f"label {label!r}"}
        best.set_focus()
        try:
            best.set_edit_text("")  # clear
        except Exception:
            send_keys("^a{DEL}")
        best.type_keys(str(value), with_spaces=True)
        if press_enter_after:
            send_keys("{ENTER}")
    except Exception as e:
        return {"ok": False, "error": f"set param failed: {e!r}"}
    return {"ok": True,
            "label": label, "value": str(value),
            "dialog_title": dlg.window_text() if dlg else None}


def gui_close_dialog(action: str = "ok",
                     layout_file: Optional[str] = None) -> Dict[str, Any]:
    """Close the foreground dialog. action ∈ {"ok", "cancel", "apply"}.
    ok    → Enter
    cancel→ Escape
    apply → click "Apply" button by name, fallback to Alt+A
    """
    g = _require_pwa()
    if g:
        return g
    act = action.lower()
    if act not in ("ok", "cancel", "apply"):
        return {"ok": False,
                "error": f"action must be ok/cancel/apply, got {action!r}"}
    try:
        if act == "ok":
            send_keys("{ENTER}")
        elif act == "cancel":
            send_keys("{ESC}")
        else:  # apply
            send_keys("%a")
    except Exception as e:
        return {"ok": False, "error": f"send_keys failed: {e!r}"}
    return {"ok": True, "action": act}


# ---------------------------------------------------------------------------
# Stream / connection drawing
# ---------------------------------------------------------------------------
def gui_connect_units(from_x: int, from_y: int,
                      to_x: int, to_y: int,
                      duration_s: float = 0.4,
                      layout_file: Optional[str] = None) -> Dict[str, Any]:
    """Wire one unit to another by dragging from the outlet point of the
    source unit to the inlet point of the destination unit. In SUMO24 this
    is a simple left-button drag between the two canvas points.
    """
    return gui_drag_from_to(int(from_x), int(from_y),
                            int(to_x), int(to_y),
                            duration_s=duration_s,
                            layout_file=layout_file)


# ---------------------------------------------------------------------------
# Ribbon-tab navigation
# ---------------------------------------------------------------------------
def gui_switch_tab(tab: str,
                   layout_file: Optional[str] = None) -> Dict[str, Any]:
    """Switch the SUMO ribbon tab. tab ∈ {Home, Configure, Models, Tools,
    Inputs, Outputs, Simulate}. Uses layout.tabs[tab] (client xy) if present;
    otherwise falls back to the default SUMO24 ribbon layout below.
    """
    g = _require_pwa()
    if g:
        return g
    lay = load_layout(layout_file)
    if not lay.get("ok"):
        return lay
    layout = lay["layout"]
    tabs_cfg = layout.get("tabs", {}) or {}
    # Defaults match a 1920-wide SUMO24 window on the home screen layout.
    default_tabs = {
        "Home":      {"x":  29, "y":  70},
        "Configure": {"x": 137, "y":  70},
        "Models":    {"x": 306, "y":  70},
        "Tools":     {"x": 470, "y":  70},
        "Inputs":    {"x": 635, "y":  70},
        "Outputs":   {"x": 799, "y":  70},
        "Simulate":  {"x": 962, "y":  70},
    }
    spec = tabs_cfg.get(tab) or default_tabs.get(tab)
    if not spec:
        return {"ok": False,
                "error": f"tab {tab!r} not in layout.tabs or defaults",
                "known_tabs": sorted(set(list(tabs_cfg.keys()) +
                                         list(default_tabs.keys())))}
    return gui_click_at(int(spec["x"]), int(spec["y"]),
                        layout_file=layout_file)


# ═══════════════════════════════════════════════════════════════════════════
# v3 — template-matching (OpenCV) for icons that hardcoded coords can't hit.
#
# Why: SUMO24's owner-drawn palette has cases where hardcoded pixel coords
# fail — e.g. an icon at a panel boundary, an icon whose visible bitmap is
# offset from its hit-test region, or layouts that shift when the user
# resizes the window. Template matching finds the icon by its appearance
# wherever it actually lives on screen, so the drag-source is always inside
# the rendered bitmap.
# ═══════════════════════════════════════════════════════════════════════════

_TEMPLATE_DIR_NAME = "gui_templates"


def _templates_dir() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    d = os.path.join(here, _TEMPLATE_DIR_NAME)
    os.makedirs(d, exist_ok=True)
    return d


def _require_cv2() -> Optional[Dict[str, Any]]:
    if not CV2_AVAILABLE:
        return {"ok": False,
                "error": "opencv-python not installed",
                "detail": _CV2_IMPORT_ERROR,
                "next_step": "pip install opencv-python-headless numpy"}
    if not PIL_AVAILABLE:
        return {"ok": False, "error": "Pillow not installed",
                "next_step": "pip install pillow"}
    return None


def gui_capture_palette_template(unit_type: str,
                                 x: int, y: int,
                                 w: int = 34,
                                 h: int = 32,
                                 layout_file: Optional[str] = None
                                 ) -> Dict[str, Any]:
    """Capture a rectangular crop of the SUMO window centred at client (x, y)
    and save it as the palette-template PNG for unit_type. Use this once,
    while the icon is clearly visible on screen, so future drops can find
    the icon by appearance regardless of layout shifts.

    Stored at PY/gui_templates/<unit_type>.png and recorded in
    layout.palette[unit_type].template so gui_drop_unit_by_template can
    look it up by name.
    """
    g = _require_pwa()
    if g:
        return g
    cv_g = _require_cv2()
    if cv_g:
        return cv_g
    lay = load_layout(layout_file)
    if not lay.get("ok"):
        return lay
    try:
        win, rect = _win_and_rect(lay["layout"])
    except RuntimeError as e:
        return {"ok": False, "error": str(e),
                "next_step": "Call launch_sumo_gui first."}
    # Convert client (x, y, w, h) to screen bbox
    sx, sy = _to_screen(rect, x, y)
    hw, hh = int(w) // 2, int(h) // 2
    bbox = (sx - hw, sy - hh, sx - hw + int(w), sy - hh + int(h))
    try:
        img = ImageGrab.grab(bbox=bbox, all_screens=True)
    except Exception as e:
        return {"ok": False, "error": f"capture failed: {e!r}"}
    out_path = os.path.join(_templates_dir(), f"{unit_type}.png")
    try:
        img.save(out_path)
    except OSError as e:
        return {"ok": False, "error": f"save failed: {e!r}"}
    # Record the template path in the layout so other tools can find it
    layout = lay["layout"]
    palette = layout.setdefault("palette", {})
    entry = palette.get(unit_type, {})
    entry["template"] = out_path
    palette[unit_type] = entry
    _save_layout(layout, lay["path"])
    return {"ok": True,
            "unit_type": unit_type,
            "template_path": out_path,
            "client_xy": [int(x), int(y)],
            "screen_bbox": list(bbox),
            "size": list(img.size)}


def gui_find_icon_by_template(unit_type: str,
                              search_bbox: Optional[list] = None,
                              threshold: float = 0.82,
                              layout_file: Optional[str] = None
                              ) -> Dict[str, Any]:
    """Find unit_type's palette icon on screen by template matching.
    Returns the centre point in SUMO client coords and the match score.

    search_bbox is an optional [left, top, right, bottom] in client coords
    to restrict the search (faster + avoids false positives on canvas
    units that look like palette icons). If omitted, scans the entire
    SUMO window.
    """
    g = _require_pwa()
    if g:
        return g
    cv_g = _require_cv2()
    if cv_g:
        return cv_g
    lay = load_layout(layout_file)
    if not lay.get("ok"):
        return lay
    layout = lay["layout"]
    palette = layout.get("palette", {})
    spec = palette.get(unit_type, {})
    tpl_path = spec.get("template")
    if not tpl_path:
        # Fall back to default location PY/gui_templates/<unit_type>.png
        candidate = os.path.join(_templates_dir(), f"{unit_type}.png")
        if os.path.isfile(candidate):
            tpl_path = candidate
        else:
            return {"ok": False,
                    "error": f"no template for {unit_type!r}",
                    "next_step": "Call gui_capture_palette_template first."}
    if not os.path.isfile(tpl_path):
        return {"ok": False,
                "error": f"template file missing: {tpl_path}",
                "next_step": "Re-capture with gui_capture_palette_template."}
    try:
        win, rect = _win_and_rect(layout)
    except RuntimeError as e:
        return {"ok": False, "error": str(e),
                "next_step": "Call launch_sumo_gui first."}
    # Capture the search area (defaults to whole window)
    if search_bbox and len(search_bbox) == 4:
        cx1, cy1, cx2, cy2 = (int(v) for v in search_bbox)
    else:
        cx1, cy1, cx2, cy2 = 0, 0, rect.right - rect.left, rect.bottom - rect.top
    sx1, sy1 = _to_screen(rect, cx1, cy1)
    sx2, sy2 = _to_screen(rect, cx2, cy2)
    try:
        screen_pil = ImageGrab.grab(bbox=(sx1, sy1, sx2, sy2), all_screens=True)
    except Exception as e:
        return {"ok": False, "error": f"capture failed: {e!r}"}
    # Convert to cv2 BGR arrays
    screen = _cv2.cvtColor(_np.array(screen_pil), _cv2.COLOR_RGB2BGR)
    template_pil = _PILImage.open(tpl_path).convert("RGB")
    template = _cv2.cvtColor(_np.array(template_pil), _cv2.COLOR_RGB2BGR)
    th, tw = template.shape[:2]
    if screen.shape[0] < th or screen.shape[1] < tw:
        return {"ok": False,
                "error": f"search region {screen.shape} smaller than "
                         f"template ({th}, {tw})"}
    # Normalised cross-correlation
    res = _cv2.matchTemplate(screen, template, _cv2.TM_CCOEFF_NORMED)
    min_val, max_val, min_loc, max_loc = _cv2.minMaxLoc(res)
    if float(max_val) < float(threshold):
        return {"ok": False,
                "error": f"best match score {max_val:.3f} below threshold "
                         f"{threshold}",
                "best_score": float(max_val),
                "best_loc_screen": [int(sx1 + max_loc[0]),
                                    int(sy1 + max_loc[1])],
                "template_size": [int(tw), int(th)],
                "next_step": "Lower threshold or re-capture the template."}
    # Centre of match in SCREEN coords
    cx_screen = sx1 + max_loc[0] + tw // 2
    cy_screen = sy1 + max_loc[1] + th // 2
    # Convert back to CLIENT coords
    client_x = cx_screen - rect.left
    client_y = cy_screen - rect.top
    return {"ok": True,
            "unit_type": unit_type,
            "score": float(max_val),
            "client_xy": [int(client_x), int(client_y)],
            "screen_xy": [int(cx_screen), int(cy_screen)],
            "template_size": [int(tw), int(th)],
            "template_path": tpl_path}


def gui_drop_unit_by_template(unit_type: str,
                              x: int, y: int,
                              search_bbox: Optional[list] = None,
                              threshold: float = 0.82,
                              duration_s: float = 0.6,
                              layout_file: Optional[str] = None
                              ) -> Dict[str, Any]:
    """Find unit_type's palette icon via template match, then drag from
    that icon's centre onto the canvas at (x, y). Both source and
    destination are SUMO client coords.

    This bypasses the hardcoded-coords path entirely — works even when
    the palette has reflowed, the icon moved due to window resize, or the
    icon's visible bitmap sits at a different offset from its UIA hit
    region.
    """
    found = gui_find_icon_by_template(unit_type,
                                      search_bbox=search_bbox,
                                      threshold=threshold,
                                      layout_file=layout_file)
    if not found.get("ok"):
        return found
    src_x, src_y = found["client_xy"]
    drag = gui_drag_from_to(int(src_x), int(src_y), int(x), int(y),
                            duration_s=duration_s,
                            layout_file=layout_file)
    if not drag.get("ok"):
        drag["template_match"] = found
        return drag
    drag["template_match_score"] = found["score"]
    drag["template_source"] = [int(src_x), int(src_y)]
    drag["unit_type"] = unit_type
    return drag
