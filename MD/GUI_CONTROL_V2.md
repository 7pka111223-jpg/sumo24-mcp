# SUMO24 GUI Control — v2 toolset (Group GG extension)

## Why this exists

The original Group GG tool `gui_add_unit_to_canvas` resolves palette icons
by their UIA accessible name (`pywinauto child_window(title=...)`). SUMO24's
process-unit palette is *owner-drawn*: the icons are bitmap blits with no
named UIA children, so the lookup raises `ElementNotFoundError` for every
unit type — confirmed with both `MBBR` and the pre-shipped `AerationTank`.

The v2 toolset bypasses the UIA tree and drives the SUMO main window with
**raw client-area pixel coordinates** plus `pywinauto.mouse` /
`pywinauto.keyboard.send_keys`. Coordinates are stored once in
`sumo_gui_layout.json` and reused thereafter.

## What was added

Code: `PY/sumo_gui.py` (functions appended after the original four MVP
helpers); `PY/server.py` (tool schemas, dispatch entries, `_exp_*`
wrappers, all in the Group GG section).

### Window helpers
| Tool | Purpose |
|---|---|
| `gui_focus_sumo` | Bring SUMO window forward; return rect. |
| `gui_get_window_rect` | Return current main-window bounds (screen coords). |

### Generic primitives
| Tool | Purpose |
|---|---|
| `gui_click_at` | Left/right/middle click at client `(x, y)`, with `clicks=1\|2` and optional `modifiers` (`+`, `^`, `%`). |
| `gui_drag_from_to` | Linearly-interpolated mouse drag from `(x1, y1)` to `(x2, y2)`. |
| `gui_send_keys` | `pywinauto.keyboard.send_keys` to the focused SUMO window. |
| `gui_type_text` | Type literal text with spaces / tabs preserved. |

### Palette calibration & coord-based unit drop
| Tool | Purpose |
|---|---|
| `gui_calibrate_palette_item` | Persist `(x, y)` (and optional display name) for a `unit_type` into `layout.palette`. |
| `gui_list_palette_items` | Return current palette table; partition into `calibrated` / `uncalibrated`. |
| `gui_drop_unit_at` | Drag the calibrated icon for `unit_type` onto canvas at `(x, y)`. No UIA lookup. |

### Unit-properties dialog
| Tool | Purpose |
|---|---|
| `gui_open_unit_properties` | Double-click canvas unit at `(x, y)`; report visible top-level windows. |
| `gui_set_param_in_dialog` | Find Edit control next to a label (e.g. "Volume") and set its value. |
| `gui_close_dialog` | OK (Enter) / Cancel (Esc) / Apply (Alt+A). |

### Stream wiring
| Tool | Purpose |
|---|---|
| `gui_connect_units` | Drag from source outlet pixel to destination inlet pixel. |

### Ribbon navigation
| Tool | Purpose |
|---|---|
| `gui_switch_tab` | Click Home/Configure/Models/Tools/Inputs/Outputs/Simulate via `layout.tabs[tab]` (fallback defaults built in). |

## Recommended workflow to add a unit (e.g. MBBR before each clarifier)

```
1.  launch_sumo_gui                        # attach to running SUMO
2.  gui_switch_tab tab=Configure           # bring up canvas + palette
3.  gui_screenshot output_dir=…            # capture for one-time calibration
4.  gui_calibrate_palette_item unit_type=MBBR x=<icon_cx> y=<icon_cy>
        # ── one-time per palette icon; pixel coords read from the screenshot
5.  gui_drop_unit_at unit_type=MBBR x=<canvas_x1> y=<canvas_y1>
6.  gui_drop_unit_at unit_type=MBBR x=<canvas_x2> y=<canvas_y2>
7.  gui_open_unit_properties x=<canvas_x1> y=<canvas_y1>
8.  gui_set_param_in_dialog label="Volume"      value="500"
9.  gui_set_param_in_dialog label="Fill ratio"  value="0.4"
10. gui_close_dialog action=ok
        # ── repeat 7–10 for the second MBBR
11. gui_connect_units from_x=<cstr_out_x>  from_y=<cstr_out_y>
                     to_x=<mbbr_in_x>      to_y=<mbbr_in_y>
        # ── plus the MBBR → Clarifier link, repeat for second train
12. gui_save_sumo target_path="F:/…/Verified TSS shock RAS 1 days.sumo"
```

The first project-by-project cost is one calibration pass (4–5 mouse-over
reads per palette icon). After that all subsequent runs reuse the saved
`sumo_gui_layout.json` and need no human-in-the-loop input.

## Layout-file schema additions

```jsonc
{
  "executable": "D:/SUMO24/Sumo24.exe",
  "window_title_regex": "(?i)(SUMO|Sumo).*",
  "palette": {
     "MBBR": {"x": 35, "y": 168, "name": "MBBR"}      // NEW: (x,y) keys
  },
  "tabs": {                                            // NEW (optional)
     "Configure": {"x": 137, "y": 70}
  }
}
```

Existing `palette` entries that only had `name` still work — they're picked
up by the old `gui_add_unit_to_canvas` path. The new `gui_drop_unit_at`
explicitly requires `(x, y)` and returns a clear error if they're missing.

## What this still doesn't do (intentional)

* No auto-discovery of palette icon coordinates. Image-template matching
  via OpenCV would be the next step; today the calibration is manual to
  keep dependencies (Pillow + pywinauto) unchanged.
* `gui_set_param_in_dialog` assumes the parameter row is `label … edit
  field` on the same row. SUMO's tabbed property panes generally are, but
  exotic layouts may need a custom locator.
* No connection rerouting. SUMO auto-routes the polyline after a drag
  between two ports; the v2 tools don't draw waypoints.
