"""
sumo_native.py — Tier-1 native .sumo composer for the SUMO24 MCP server.

THE PROBLEM THIS MODULE SOLVES
------------------------------
A real SUMO24 `.sumo` file is a zip archive whose runnable core is a
compiled `sumoproject.dll` (C# / PE32+). SUMO24's own compiler emits
that DLL from a SumoSlang plant definition, and the DLL embeds plant-
specific bindings (unit ids, kinetic equations, ODE structure). The
MCP server has no way to compile that DLL on its own.

The historical `build_sumo_pack` path therefore stops at a directory of
source artefacts and asks the user to finish the build inside SUMO24
GUI by hand. `apply_schematic_to_baseline` goes one step further by
copying a baseline (.sumo + .dll) pair to a new location, but it does
NOT modify the internal members of the .sumo zip — the new file is
byte-identical to the baseline and the parameter overrides live in a
sibling state.xml.

This module is the missing piece: a true native composer that opens
the baseline zip, rewrites the parameter-bearing members in place
(parameters.txt, Influent*_Table*.tsv, notes.rtf, userscript.txt),
keeps the DLL and every DLL-bound member byte-perfect, and repackages
the result so it can be opened by SUMO24 directly.

WHAT THIS MODULE IS NOT
-----------------------
This is not a SumoSlang compiler. The topology of the produced .sumo is
the topology of the baseline. To run a brand new topology you must
first compile that topology once inside SUMO24 GUI to obtain a matching
sumoproject.dll, then add the pair to the baseline library and target
it from here.

PUBLIC API
----------
- build_native_sumo(...)        compose a new .sumo from baseline + schematic
- topology_match_report(...)    preview compatibility before building
- auto_match_units(...)         heuristic schematic→baseline unit map by type

All functions are pure-stdlib and side-effect-free until the final
write step. They never touch DTT.
"""

from __future__ import annotations

import datetime as _dt
import hashlib as _hashlib
import io as _io
import json as _json
import re as _re
import shutil as _shutil
import zipfile as _zipfile
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

# Schematic parsing piggybacks on the existing parser when available.
try:
    import schematic_parser as _sp  # type: ignore
    _SP_AVAILABLE = True
except Exception:
    _sp = None  # type: ignore
    _SP_AVAILABLE = False


# ─── INTERNAL FILE ROLES ────────────────────────────────────────────────────
#
# Every member of a SUMO24 .sumo zip falls into one of three buckets:
#
# DLL_BOUND   — embeds compiled or generated references to specific unit
#               ids in the DLL. Must be copied byte-for-byte from baseline.
# PARAM_BEARING — contains numeric parameter values keyed by Sumo path.
#               Safe to rewrite as long as keys are preserved.
# COSMETIC    — user-facing text / images. Safe to overwrite.
#
# Anything not classified is treated as DLL_BOUND (the conservative choice).

_PARAM_BEARING_NAMES = frozenset({
    "parameters.txt",
})

_PARAM_BEARING_PATTERNS = (
    _re.compile(r"^Influent\d+(?:_\d+)*_Table\d+\.tsv$"),
    _re.compile(r"^Save_Influent\d+(?:_\d+)*_Table\d+$"),
)

_COSMETIC_NAMES = frozenset({
    "notes.rtf",
    "userscript.txt",
    "plant.png",
})


def _classify_member(name: str) -> str:
    if name in _PARAM_BEARING_NAMES:
        return "PARAM_BEARING"
    if name in _COSMETIC_NAMES:
        return "COSMETIC"
    for pat in _PARAM_BEARING_PATTERNS:
        if pat.match(name):
            return "PARAM_BEARING"
    return "DLL_BOUND"


# ─── BASELINE INTROSPECTION ─────────────────────────────────────────────────


def _sha256(data: bytes) -> str:
    return _hashlib.sha256(data).hexdigest()


_PARAM_LINE_RE = _re.compile(
    r"^Sumo__Plant__(?P<unit>[A-Za-z0-9_]+)__param__(?P<key>[A-Za-z0-9_\[\]]+)\t"
    r"(?P<value>[^\t\r\n]*)"
)


def parse_baseline(baseline_sumo: Path) -> Dict[str, Any]:
    """
    Read a baseline .sumo zip and return a structural snapshot:
        {
          "members"            : ordered list of member names,
          "member_roles"       : {name: classification},
          "param_keys"         : {(unit_id, key): str_value},
          "unit_ids"           : sorted list of unit ids,
          "influent_tables"    : list of TSV member names,
          "dll_present"        : bool,
          "dll_sha256"         : str,
          "bytes"              : file size,
        }
    """
    if not baseline_sumo.exists():
        raise FileNotFoundError(f"baseline_sumo not found: {baseline_sumo}")
    if not _zipfile.is_zipfile(baseline_sumo):
        raise ValueError(f"baseline_sumo is not a zip container: {baseline_sumo}")

    members: List[str] = []
    member_roles: Dict[str, str] = {}
    param_keys: "OrderedDict[Tuple[str, str], str]" = OrderedDict()
    influent_tables: List[str] = []
    dll_present = False
    dll_sha = ""

    with _zipfile.ZipFile(baseline_sumo, "r") as zf:
        for info in zf.infolist():
            members.append(info.filename)
            role = _classify_member(info.filename)
            member_roles[info.filename] = role
            if info.filename == "parameters.txt":
                text = zf.read(info.filename).decode("utf-8", errors="replace")
                for line in text.splitlines():
                    m = _PARAM_LINE_RE.match(line)
                    if m:
                        param_keys[(m.group("unit"), m.group("key"))] = m.group("value")
            elif info.filename.startswith("Influent") and info.filename.endswith(".tsv"):
                influent_tables.append(info.filename)
            elif info.filename == "sumoproject.dll":
                dll_present = True
                dll_sha = _sha256(zf.read(info.filename))

    unit_ids = sorted({u for (u, _k) in param_keys.keys()})

    return {
        "members":         members,
        "member_roles":    member_roles,
        "param_keys":      param_keys,
        "unit_ids":        unit_ids,
        "influent_tables": influent_tables,
        "dll_present":     dll_present,
        "dll_sha256":      dll_sha,
        "bytes":           baseline_sumo.stat().st_size,
    }


# ─── SCHEMATIC NORMALISATION ────────────────────────────────────────────────


def _load_schematic(
    schematic: "dict | str | Path | None",
    *,
    schematic_html: "str | Path | None" = None,
    schematic_json: "str | Path | None" = None,
) -> Dict[str, Any]:
    """Accept any of dict / html path / json path and return the parsed dict."""
    if isinstance(schematic, dict):
        return schematic
    if isinstance(schematic, (str, Path)):
        p = Path(schematic)
        if p.suffix.lower() == ".html" and not schematic_html:
            schematic_html = p
        elif p.suffix.lower() == ".json" and not schematic_json:
            schematic_json = p
        else:
            raise ValueError(
                f"Don't know how to load schematic from {p} "
                "(expected .html or .json)"
            )

    if schematic_html:
        if not _SP_AVAILABLE:
            raise ImportError("schematic_parser not importable")
        return _sp.load_schematic(str(schematic_html))
    if schematic_json:
        with open(schematic_json, "r", encoding="utf-8") as f:
            return _json.load(f)

    raise ValueError(
        "Provide schematic (dict), schematic_html, or schematic_json"
    )


# ─── UNIT MAPPING ───────────────────────────────────────────────────────────
#
# Schematic unit ids ("U1", "U2", "OxidationDitch1") will rarely match
# baseline unit ids ("Influent1", "CSTR7_2_1") exactly. Three options:
#
#   1. User supplies an explicit mapping {schematic_id: baseline_id}.
#   2. Schematic ids are already baseline ids (verified by validation).
#   3. Auto-match by SumoSlang class — best-effort, may need adjustment.
#
# auto_match_units implements option 3.


# Class hint per schematic type, used to pair schematic units with baseline
# unit ids that share the same SumoSlang class.
_TYPE_TO_CLASS = {
    "influent":             "Influent",
    "effluent":             "Effluent",      # heuristic only
    "ras_flow":             "Effluent",
    "was_flow":             "Effluent",
    "screen":               "Pointsettler",
    "grit_chamber":         "Pointsettler",
    "primary_clarifier":    "Primaryclarifier",
    "anaerobic_zone":       "CSTR",
    "anoxic_zone":          "CSTR",
    "aerobic_zone":         "CSTR",
    "oxidation_ditch":      "CSTR",
    "mbbr":                 "Biofilmcstr",
    "secondary_clarifier":  "Clarifier",     # baseline uses "Clarifier*"
    "tertiary_filter":      "Pointsettler",
    "disinfection":         "Pointsettler",
    "dewatering":           "Pointsettler",
    "ras_pump":             "Pump",
    "was_pump":             "Pump",
    "internal_recycle":     "Pump",
    "thickener":            "Thickener",
    "anaerobic_digester":   "Digester",
    "splitter":             "Sideflowdivider",
    "sludge_splitter":      "Sludgesplitter",
    "combiner":             "Combiner",
}


def _baseline_class_of(unit_id: str) -> str:
    """Return the SumoSlang class hint stripped from a baseline unit id."""
    # baseline ids look like "Clarifier3_1", "CSTR7_2_1", "Influent1",
    # "Sideflowdivider2". Strip trailing digits/underscores.
    return _re.sub(r"[\d_]+$", "", unit_id) or unit_id


def auto_match_units(
    schematic_units: Iterable[Mapping[str, Any]],
    baseline_unit_ids: Iterable[str],
) -> Dict[str, str]:
    """
    Heuristic mapping from schematic.unit.id → baseline.unit_id by class.

    Returns the largest greedy matching; schematic units with no match
    are absent from the returned dict.
    """
    bases = list(baseline_unit_ids)
    pool: Dict[str, List[str]] = {}
    for uid in bases:
        cls = _baseline_class_of(uid)
        pool.setdefault(cls, []).append(uid)
    # stabilise order
    for k in pool:
        pool[k].sort()

    out: Dict[str, str] = {}
    for u in schematic_units:
        cls = _TYPE_TO_CLASS.get(u.get("type", ""), "")
        bucket = pool.get(cls)
        if not bucket:
            continue
        out[u["id"]] = bucket.pop(0)
    return out


def topology_match_report(
    schematic: Mapping[str, Any],
    baseline_info: Mapping[str, Any],
    *,
    user_mapping: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    """
    Preview whether a schematic is compatible with a baseline. Returns:
        {
          "ok"            : bool — every schematic unit got a baseline target
          "mapping"       : final {schematic_id: baseline_id} mapping
          "unmapped"      : schematic ids with no baseline target
          "unused_targets": baseline ids not consumed by the mapping
          "warnings"      : list of strings
        }
    """
    sch_units = schematic.get("units") or []
    base_ids: List[str] = list(baseline_info.get("unit_ids") or [])

    explicit = dict(user_mapping or {})
    heuristic = auto_match_units(
        (u for u in sch_units if u["id"] not in explicit),
        (b for b in base_ids if b not in set(explicit.values())),
    )
    mapping = {**heuristic, **explicit}  # explicit wins

    sch_ids = {u["id"] for u in sch_units}
    unmapped = sorted(sch_ids - mapping.keys())
    unused = sorted(set(base_ids) - set(mapping.values()))

    warnings: List[str] = []
    if unmapped:
        warnings.append(
            f"{len(unmapped)} schematic unit(s) have no baseline target "
            f"and will be skipped: {unmapped[:8]}"
            + ("…" if len(unmapped) > 8 else "")
        )
    if unused:
        warnings.append(
            f"{len(unused)} baseline unit(s) are not referenced by the "
            f"schematic; their parameters stay at baseline values."
        )
    # warn on any heuristic match that crossed obvious type lines
    for sid, bid in heuristic.items():
        bcls = _baseline_class_of(bid)
        sch_u = next((u for u in sch_units if u["id"] == sid), None)
        if not sch_u:
            continue
        expected = _TYPE_TO_CLASS.get(sch_u.get("type", ""), "")
        if expected and expected != bcls:
            warnings.append(
                f"Heuristic mapped schematic {sid} ({sch_u.get('type')}) "
                f"→ baseline {bid} ({bcls}); class hint differs"
            )

    return {
        "ok":             not unmapped,
        "mapping":        mapping,
        "unmapped":       unmapped,
        "unused_targets": unused,
        "warnings":       warnings,
    }


# ─── REWRITERS ──────────────────────────────────────────────────────────────


def rewrite_parameters_txt(
    baseline_text: str,
    schematic: Mapping[str, Any],
    mapping: Mapping[str, str],
    *,
    baseline_params: Mapping[Tuple[str, str], str],
) -> Tuple[str, Dict[str, Any]]:
    """
    Apply schematic parameter values onto baseline parameters.txt.

    Only overrides values for (baseline_unit_id, param_key) pairs that
    already exist in the baseline. Schematic parameters whose
    `sumo_variable` does not resolve are reported in `skipped`.

    Returns (new_text, info).
    """
    # Build an override map keyed by (baseline_unit, param_key)
    overrides: Dict[Tuple[str, str], str] = {}
    skipped_params: List[Dict[str, Any]] = []
    applied: List[Dict[str, Any]] = []

    for u in schematic.get("units", []) or []:
        sid = u.get("id")
        bid = mapping.get(sid)
        if not bid:
            continue
        params = u.get("parameters") or []
        if isinstance(params, dict):
            params = [{"key": k, "value": v} for k, v in params.items()]
        for p in params:
            sv = p.get("sumo_variable") or ""
            # We want the trailing "name" component of the sumo_variable.
            # Format is typically "Sumo__Plant__<unit>__param__<key>".
            key = ""
            m = _re.search(r"__param__([A-Za-z0-9_\[\]]+)$", sv)
            if m:
                key = m.group(1)
            else:
                key = p.get("key", "")
            if not key:
                skipped_params.append(
                    {"schematic_unit": sid, "key_missing": True}
                )
                continue
            if (bid, key) not in baseline_params:
                skipped_params.append(
                    {"schematic_unit": sid, "baseline_unit": bid,
                     "key": key, "reason": "key not in baseline parameters.txt"}
                )
                continue
            overrides[(bid, key)] = _fmt_value(p.get("value"))
            applied.append(
                {"baseline_unit": bid, "key": key,
                 "value": overrides[(bid, key)],
                 "from_schematic_unit": sid}
            )

    # Walk the baseline text line-by-line and substitute matched values.
    out_lines: List[str] = []
    replaced_count = 0
    for line in baseline_text.splitlines():
        m = _PARAM_LINE_RE.match(line)
        if m:
            key_tuple = (m.group("unit"), m.group("key"))
            if key_tuple in overrides:
                new_val = overrides[key_tuple]
                prefix = f"Sumo__Plant__{m.group('unit')}__param__{m.group('key')}"
                # preserve any trailing columns (waviness fields etc.)
                tail = line[m.end():]
                line = f"{prefix}\t{new_val}{tail}"
                replaced_count += 1
        out_lines.append(line)

    new_text = "\n".join(out_lines)
    # Preserve trailing newline behaviour of the source
    if baseline_text.endswith(("\n", "\r")) and not new_text.endswith("\n"):
        new_text += "\n"

    return new_text, {
        "applied":   applied,
        "skipped":   skipped_params,
        "replaced_lines": replaced_count,
        "override_count": len(overrides),
    }


def _fmt_value(v: Any) -> str:
    """Format a Python value the way SUMO writes parameters.txt entries."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (int,)):
        return str(v)
    if isinstance(v, float):
        # Preserve 1E-50 style for very small numbers, 6 sig figs otherwise.
        if v == 0:
            return "0"
        if abs(v) < 1e-4 or abs(v) >= 1e6:
            return f"{v:.6E}".replace("E-0", "E-").replace("E+0", "E+")
        return f"{v:g}"
    return str(v)


_INFLUENT_HEADER_RE = _re.compile(r"^msecs\t(.+)$", _re.MULTILINE)


def rewrite_influent_table(
    baseline_text: str,
    schematic: Mapping[str, Any],
    *,
    baseline_unit_id: str,
    schematic_influent_id: Optional[str] = None,
) -> Optional[str]:
    """
    Regenerate an Influent*_Table*.tsv from the schematic's influent
    profile, if the schematic provides one. Returns None if no profile
    is available (caller should keep the baseline text unchanged).

    The baseline header is preserved verbatim — only the data rows are
    replaced. Influent quantities not present in the schematic profile
    are filled with '?' so SUMO uses the constant input value from
    parameters.txt for that column.
    """
    profile = (schematic.get("influent_profile") or {})
    if isinstance(profile, list):
        # alternative shape: list of {unit_id, samples}
        profile = next(
            (p for p in profile if p.get("unit_id") == schematic_influent_id),
            {},
        )
    samples = profile.get("samples") or profile.get("rows")
    if not samples:
        return None

    # Header from baseline
    header_match = _INFLUENT_HEADER_RE.search(baseline_text)
    if not header_match:
        return None
    header_line = baseline_text.splitlines()[0]
    cols = header_line.split("\t")[1:]   # drop "msecs"

    # Build a key index for samples: column name → schematic key
    # samples may use either the full Sumo__Plant__Influent1__param__Q
    # form or a short form like "Q". Try both.
    out_lines: List[str] = [header_line]
    for row in samples:
        msecs = row.get("msecs") or row.get("t_ms") or row.get("time_ms")
        if msecs is None:
            t_d = row.get("t_d") or row.get("day")
            if t_d is None:
                continue
            msecs = int(float(t_d) * 86_400_000)
        row_vals: List[str] = [str(int(msecs))]
        for c in cols:
            short = c.split("__")[-1]
            v = row.get(c)
            if v is None:
                v = row.get(short)
            row_vals.append(_fmt_value(v) if v is not None else "?")
        out_lines.append("\t".join(row_vals))
    new_text = "\r\n".join(out_lines)
    if not new_text.endswith("\r\n"):
        new_text += "\r\n"
    return new_text


_RTF_PROVENANCE_BLOCK = (
    r"{{\b Generated by SUMO24 MCP sumo_native\b0\par "
    r"Schematic: {schematic_name}\par "
    r"Baseline:  {baseline_name}\par "
    r"Build:     {iso}\par "
    r"DLL SHA-256: {dll_sha}\par "
    r"--\par }}"
)


def rewrite_notes_rtf(
    baseline_text: str,
    schematic: Mapping[str, Any],
    *,
    baseline_name: str,
    dll_sha: str,
) -> str:
    """Prepend a provenance block at the start of the RTF body."""
    sch_name = (
        (schematic.get("meta") or {}).get("plant_name")
        or "(unnamed schematic)"
    )
    provenance = _RTF_PROVENANCE_BLOCK.format(
        schematic_name=_rtf_escape(sch_name),
        baseline_name=_rtf_escape(baseline_name),
        iso=_dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        dll_sha=dll_sha[:16] + "…",
    )
    # Insert right after the first \pard line so the formatting stays sane.
    m = _re.search(r"(\\pard[^\r\n]*)", baseline_text)
    if not m:
        return baseline_text  # leave untouched if shape unexpected
    insert_at = m.end()
    return baseline_text[:insert_at] + " " + provenance + baseline_text[insert_at:]


def _rtf_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("{", r"\{").replace("}", r"\}")


# ─── COMPOSER ───────────────────────────────────────────────────────────────


def build_native_sumo(
    *,
    schematic: "dict | str | Path | None" = None,
    schematic_html: "str | Path | None" = None,
    schematic_json: "str | Path | None" = None,
    baseline_sumo: "str | Path",
    baseline_dll: "Optional[str | Path]" = None,
    output_sumo: "str | Path",
    unit_mapping: Optional[Mapping[str, str]] = None,
    overwrite: bool = False,
    strict: bool = True,
    write_companion_dll: bool = True,
) -> Dict[str, Any]:
    """
    Build a real, runnable .sumo file from a baseline + schematic.

    Strategy
    --------
    Open the baseline zip, rewrite parameter-bearing members from the
    schematic, copy every DLL-bound member byte-for-byte, and write the
    result as a new zip. The companion sumoproject.dll is copied beside
    the output (SUMO24 looks for it as a sibling, not inside the zip).

    Returns a structured summary including the mapping used, byte
    counts, members written, parameter overrides applied, and a
    diagnose-style sanity check.
    """
    baseline_sumo = Path(baseline_sumo)
    output_sumo = Path(output_sumo)
    if output_sumo.suffix.lower() != ".sumo":
        output_sumo = output_sumo.with_suffix(".sumo")

    if output_sumo.exists() and not overwrite:
        return {
            "ok": False,
            "error": f"output exists: {output_sumo} (pass overwrite=true to replace)",
        }

    sch = _load_schematic(
        schematic, schematic_html=schematic_html, schematic_json=schematic_json
    )
    if not sch.get("units"):
        return {"ok": False, "error": "schematic has no units"}

    info = parse_baseline(baseline_sumo)
    if not info["dll_present"]:
        return {
            "ok": False,
            "error": "baseline_sumo does not contain sumoproject.dll inside the zip",
        }

    report = topology_match_report(sch, info, user_mapping=unit_mapping)
    if strict and not report["ok"]:
        return {
            "ok":      False,
            "stage":   "topology_match",
            "error":   "schematic has units with no baseline target",
            "report":  report,
            "hint":    (
                "Either pass unit_mapping={schematic_id: baseline_id, ...} "
                "or rebuild the baseline so it includes every required class."
            ),
        }

    output_sumo.parent.mkdir(parents=True, exist_ok=True)

    # ── compose the new zip in memory, then write atomically ───────────────
    buf = _io.BytesIO()
    members_written: List[Dict[str, Any]] = []
    param_rewrite_info: Dict[str, Any] = {}
    influent_rewrites: List[Dict[str, Any]] = []

    with _zipfile.ZipFile(baseline_sumo, "r") as zin, \
         _zipfile.ZipFile(buf, "w", compression=_zipfile.ZIP_DEFLATED) as zout:

        for src_info in zin.infolist():
            name = src_info.filename
            role = info["member_roles"][name]
            data = zin.read(name)

            if name == "parameters.txt":
                new_text, param_rewrite_info = rewrite_parameters_txt(
                    data.decode("utf-8", errors="replace"),
                    sch,
                    report["mapping"],
                    baseline_params=info["param_keys"],
                )
                data = new_text.encode("utf-8")
            elif role == "PARAM_BEARING" and name.startswith("Influent"):
                # Pick the schematic influent id to use for this baseline table.
                base_unit = name.split("_", 1)[0]   # "Influent1"
                new_text = rewrite_influent_table(
                    data.decode("utf-8", errors="replace"),
                    sch,
                    baseline_unit_id=base_unit,
                )
                if new_text is not None:
                    influent_rewrites.append({
                        "member": name,
                        "rows":   new_text.count("\n"),
                    })
                    data = new_text.encode("utf-8")
            elif name == "notes.rtf":
                new_text = rewrite_notes_rtf(
                    data.decode("ascii", errors="replace"),
                    sch,
                    baseline_name=baseline_sumo.name,
                    dll_sha=info["dll_sha256"],
                )
                data = new_text.encode("ascii", errors="replace")
            # Everything else passes through unchanged.

            # Preserve original compression behaviour where reasonable.
            zinfo_out = _zipfile.ZipInfo(filename=name, date_time=src_info.date_time)
            zinfo_out.compress_type = src_info.compress_type
            zinfo_out.external_attr = src_info.external_attr
            zout.writestr(zinfo_out, data)
            members_written.append({"name": name, "role": role, "bytes": len(data)})

    output_sumo.write_bytes(buf.getvalue())

    # Sanity: verify zip
    is_zip = _zipfile.is_zipfile(output_sumo)
    members_count = 0
    if is_zip:
        with _zipfile.ZipFile(output_sumo, "r") as zf:
            members_count = len(zf.namelist())

    # Companion DLL
    companion: Dict[str, Any] = {"requested": write_companion_dll, "written": False}
    if write_companion_dll:
        src_dll = Path(baseline_dll) if baseline_dll else None
        if not src_dll:
            # Try the DLL bundled inside the baseline zip itself.
            with _zipfile.ZipFile(baseline_sumo, "r") as zf:
                inner_dll = zf.read("sumoproject.dll")
            dst = output_sumo.with_name("sumoproject.dll")
            dst.write_bytes(inner_dll)
            companion.update({
                "written": True,
                "source":  f"{baseline_sumo.name}::sumoproject.dll",
                "target":  str(dst),
                "bytes":   len(inner_dll),
                "sha256":  _sha256(inner_dll),
            })
        elif src_dll.exists():
            dst = output_sumo.with_name("sumoproject.dll")
            _shutil.copy2(src_dll, dst)
            companion.update({
                "written": True,
                "source":  str(src_dll),
                "target":  str(dst),
                "bytes":   dst.stat().st_size,
                "sha256":  _sha256(dst.read_bytes()),
            })
        else:
            companion["error"] = f"baseline_dll not found: {src_dll}"

    return {
        "ok":                 is_zip and members_count == len(info["members"]),
        "output_sumo":        str(output_sumo),
        "bytes":              output_sumo.stat().st_size,
        "members_written":    len(members_written),
        "members_expected":   len(info["members"]),
        "is_valid_zip":       is_zip,
        "baseline":           {
            "path":      str(baseline_sumo),
            "members":   len(info["members"]),
            "dll_sha256": info["dll_sha256"],
        },
        "topology_match":     report,
        "parameter_rewrite":  param_rewrite_info,
        "influent_rewrites":  influent_rewrites,
        "companion_dll":      companion,
        "note": (
            "Topology of this .sumo equals the baseline's topology. "
            "Only parameter values have been substituted from the schematic. "
            "If you need a different topology, compile a new baseline once "
            "inside SUMO24 GUI and target it from here."
        ),
    }


__all__ = [
    "build_native_sumo",
    "topology_match_report",
    "auto_match_units",
    "parse_baseline",
    "rewrite_parameters_txt",
    "rewrite_influent_table",
    "rewrite_notes_rtf",
]
