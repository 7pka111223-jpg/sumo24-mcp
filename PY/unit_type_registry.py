"""
unit_type_registry.py
─────────────────────
Python mirror of the JavaScript UNIT_TYPES object inside
wwtp_schematic_template.html.  KEEP THE TWO IN SYNC — the schematic parser
relies on these keys to validate schematic JSON.

If you add a new unit type to the HTML, add it here too.  The parser will
raise an "unknown unit type" error against schematics that reference any
key not present below.
"""
from __future__ import annotations
from typing import Any

UNIT_TYPES: dict[str, dict[str, Any]] = {
    # ── Boundaries ────────────────────────────────────────────────
    "influent": {
        "category": "boundary", "label": "Influent", "kind": "Boundary",
        "sumo_template": "Sumo__Plant__Influent", "sumo_unit_class": "Influent",
        "parameters": {
            "Q":    {"unit": "m³/d",   "sumo": "param__Q",    "desc": "Influent flow"},
            "T":    {"unit": "°C",     "sumo": "param__T",    "desc": "Temperature"},
            "XCOD": {"unit": "mg/L",   "sumo": "param__XCOD", "desc": "Total COD"},
            "XTKN": {"unit": "mg N/L", "sumo": "param__XTKN", "desc": "Total TKN"},
            "XTP":  {"unit": "mg P/L", "sumo": "param__XTP",  "desc": "Total P"},
            "XTSS": {"unit": "mg/L",   "sumo": "param__XTSS", "desc": "Total TSS"},
        },
    },
    "effluent": {
        "category": "boundary", "label": "Effluent", "kind": "Boundary",
        "sumo_template": "Sumo__Plant__Effluent", "sumo_unit_class": "Effluent",
        "parameters": {},
    },
    "ras_flow": {
        # RAS-Flow boundary — virtual recycle endpoint. Used to terminate / mark
        # a Return Activated Sludge line on the schematic. The actual hydraulics
        # are handled by the Sludge Splitter / RAS Pump unit; this node carries
        # the design RAS flow and ratio metadata for the loop.
        "category": "boundary", "label": "RAS Flow", "kind": "Boundary · Recycle",
        "sumo_template": "Sumo__Plant__RAS_Flow", "sumo_unit_class": "RecycleStream",
        "parameters": {
            "Q":     {"unit": "m³/d", "sumo": "param__Q",     "desc": "RAS design flow"},
            "ratio": {"unit": "–",    "sumo": "param__ratio", "desc": "RAS ratio Q_RAS/Q_in"},
        },
    },
    "was_flow": {
        # WAS-Flow boundary — sludge-out terminal (mermaid 'Waste / Sludge Processing').
        "category": "boundary", "label": "WAS Flow", "kind": "Boundary · Waste",
        "sumo_template": "Sumo__Plant__WAS_Flow", "sumo_unit_class": "Effluent",
        "parameters": {
            "Q":          {"unit": "m³/d", "sumo": "param__Q",       "desc": "WAS design flow"},
            "target_SRT": {"unit": "d",    "sumo": "param__targSRT", "desc": "Target SRT"},
        },
    },

    # ── Pre-treatment ─────────────────────────────────────────────
    "screen": {
        "category": "pretreatment", "label": "Screen", "kind": "Pretreatment",
        "sumo_template": "Sumo__Plant__Screen", "sumo_unit_class": "PointSettler",
        "parameters": {"removalTSS": {"unit": "–", "sumo": "param__rTSS", "desc": "TSS removal fraction"}},
    },
    "grit_chamber": {
        "category": "pretreatment", "label": "Grit Chamber", "kind": "Pretreatment",
        "color": "#7e8a8b",
        "sumo_template": "Sumo__Plant__GritChamber", "sumo_unit_class": "PointSettler",
        "parameters": {
            "V":          {"value": 50,   "unit": "m³", "sumo": "param__V",     "desc": "Chamber volume"},
            "depth":      {"value": 2.0,  "unit": "m",  "sumo": "param__depth", "desc": "Side water depth"},
            "removalTSS": {"value": 0.10, "unit": "–",  "sumo": "param__rTSS",  "desc": "TSS (grit) removal fraction"},
        },
    },

    # ── Primary ───────────────────────────────────────────────────
    "primary_clarifier": {
        "category": "primary", "label": "Primary Clarifier", "kind": "Primary",
        "sumo_template": "Sumo__Plant__Primary", "sumo_unit_class": "PrimaryClarifier",
        "parameters": {
            "A":           {"unit": "m²",   "sumo": "param__A",     "desc": "Surface area"},
            "depth":       {"unit": "m",    "sumo": "param__depth", "desc": "Side water depth"},
            "Q_underflow": {"unit": "m³/d", "sumo": "param__Qu",    "desc": "Underflow rate"},
            "removalTSS":  {"unit": "–",    "sumo": "param__rTSS",  "desc": "TSS removal fraction"},
        },
    },

    # ── Biological ────────────────────────────────────────────────
    "anaerobic_zone": {
        "category": "biological", "label": "Anaerobic Zone", "kind": "Biological",
        "sumo_template": "Sumo__Plant__Anaerobic", "sumo_unit_class": "CSTR",
        "parameters": {
            "V":     {"unit": "m³",      "sumo": "param__V",     "desc": "Reactor volume"},
            "DOmax": {"unit": "mg O₂/L", "sumo": "param__DOmax", "desc": "Max DO (no aeration)"},
        },
    },
    "anoxic_zone": {
        "category": "biological", "label": "Anoxic Zone", "kind": "Biological",
        "sumo_template": "Sumo__Plant__Anoxic", "sumo_unit_class": "CSTR",
        "parameters": {
            "V":     {"unit": "m³",      "sumo": "param__V",     "desc": "Reactor volume"},
            "DOmax": {"unit": "mg O₂/L", "sumo": "param__DOmax", "desc": "Max DO"},
        },
    },
    "aerobic_zone": {
        "category": "biological", "label": "Aerobic Zone", "kind": "Biological",
        "sumo_template": "Sumo__Plant__Aerobic", "sumo_unit_class": "CSTR",
        "parameters": {
            "V":          {"unit": "m³",      "sumo": "param__V",          "desc": "Reactor volume"},
            "DOsetpoint": {"unit": "mg O₂/L", "sumo": "param__DOsetpoint", "desc": "DO setpoint"},
            "KLa":        {"unit": "1/d",     "sumo": "param__KLa",        "desc": "Oxygen transfer coeff"},
        },
    },
    "oxidation_ditch": {
        "category": "biological", "label": "Oxidation Ditch", "kind": "Biological",
        "sumo_template": "Sumo__Plant__OxDitch", "sumo_unit_class": "CSTR",
        "parameters": {
            "V":                {"unit": "m³",      "sumo": "param__V",          "desc": "Total volume (two trains)"},
            "DOsetpoint":       {"unit": "mg O₂/L", "sumo": "param__DOsetpoint", "desc": "DO setpoint (aerobic zone)"},
            "aerated_fraction": {"unit": "–",       "sumo": "param__faer",       "desc": "Aerated volume fraction"},
        },
    },
    "mbbr": {
        "category": "biological", "label": "MBBR", "kind": "Biofilm",
        "sumo_template": "Sumo__Plant__MBBR", "sumo_unit_class": "BiofilmCSTR",
        "parameters": {
            "V":          {"unit": "m³",      "sumo": "param__V",          "desc": "Reactor volume"},
            "fill_ratio": {"unit": "–",       "sumo": "param__fcarrier",   "desc": "Carrier fill ratio"},
            "DOsetpoint": {"unit": "mg O₂/L", "sumo": "param__DOsetpoint", "desc": "DO setpoint"},
        },
    },

    # ── Separation ────────────────────────────────────────────────
    "secondary_clarifier": {
        "category": "separation", "label": "Secondary Clarifier", "kind": "Separation",
        "sumo_template": "Sumo__Plant__Final", "sumo_unit_class": "Settler1D",
        "parameters": {
            "A":     {"unit": "m²",   "sumo": "param__A",     "desc": "Total surface area"},
            "depth": {"unit": "m",    "sumo": "param__depth", "desc": "Side water depth"},
            "SVI":   {"unit": "mL/g", "sumo": "param__SVI",   "desc": "Sludge Volume Index"},
            "v0":    {"unit": "m/d",  "sumo": "param__v0",    "desc": "Vesilind v0"},
        },
    },
    "tertiary_filter": {
        "category": "tertiary", "label": "Tertiary Filter", "kind": "Tertiary",
        "sumo_template": "Sumo__Plant__TertFilter", "sumo_unit_class": "PointSettler",
        "parameters": {
            "removalTSS": {"unit": "–", "sumo": "param__rTSS", "desc": "TSS removal fraction"},
            "removalTP":  {"unit": "–", "sumo": "param__rTP",  "desc": "TP removal fraction"},
        },
    },
    "disinfection": {
        "category": "tertiary", "label": "Disinfection", "kind": "Tertiary",
        "sumo_template": "Sumo__Plant__Disinfect", "sumo_unit_class": "PointSettler",
        "parameters": {"dose": {"unit": "mg/L", "sumo": "param__dose", "desc": "Chemical dose"}},
    },

    # ── Recycle / Pumps ───────────────────────────────────────────
    "ras_pump": {
        "category": "recycle", "label": "RAS Pump", "kind": "Recycle",
        "sumo_template": "Sumo__Plant__RAS_Pump", "sumo_unit_class": "Pump",
        "parameters": {
            "Q":     {"unit": "m³/d", "sumo": "param__Q",     "desc": "RAS flow rate"},
            "ratio": {"unit": "–",    "sumo": "param__ratio", "desc": "RAS ratio (Q_RAS / Q_in)"},
        },
    },
    "was_pump": {
        "category": "recycle", "label": "WAS Pump", "kind": "Recycle",
        "sumo_template": "Sumo__Plant__WAS_Pump", "sumo_unit_class": "Pump",
        "parameters": {
            "Q":          {"unit": "m³/d", "sumo": "param__Q",       "desc": "WAS flow rate"},
            "target_SRT": {"unit": "d",    "sumo": "param__targSRT", "desc": "Target Solids Retention Time"},
        },
    },
    "internal_recycle": {
        "category": "recycle", "label": "Internal Recycle", "kind": "Recycle",
        "sumo_template": "Sumo__Plant__IR_Pump", "sumo_unit_class": "Pump",
        "parameters": {
            "Q":     {"unit": "m³/d", "sumo": "param__Q",     "desc": "NO3 recycle flow"},
            "ratio": {"unit": "–",    "sumo": "param__ratio", "desc": "Recycle ratio"},
        },
    },

    # ── Sludge handling ───────────────────────────────────────────
    "thickener": {
        "category": "sludge", "label": "Sludge Thickener", "kind": "Sludge",
        "sumo_template": "Sumo__Plant__Thickener", "sumo_unit_class": "Thickener",
        "parameters": {
            "A":           {"unit": "m²",   "sumo": "param__A",  "desc": "Surface area"},
            "Q_underflow": {"unit": "m³/d", "sumo": "param__Qu", "desc": "Underflow rate"},
        },
    },
    "anaerobic_digester": {
        "category": "sludge", "label": "Anaerobic Digester", "kind": "Sludge",
        "sumo_template": "Sumo__Plant__Digester", "sumo_unit_class": "Digester",
        "parameters": {
            "V":   {"unit": "m³", "sumo": "param__V",   "desc": "Digester volume"},
            "T":   {"unit": "°C", "sumo": "param__T",   "desc": "Operating temperature"},
            "HRT": {"unit": "d",  "sumo": "param__HRT", "desc": "Hydraulic retention time"},
        },
    },
    "dewatering": {
        "category": "sludge", "label": "Dewatering", "kind": "Sludge",
        "sumo_template": "Sumo__Plant__Dewater", "sumo_unit_class": "PointSettler",
        "parameters": {"cake_TS": {"unit": "–", "sumo": "param__cakeTS", "desc": "Cake dryness fraction"}},
    },

    # ── Other ─────────────────────────────────────────────────────
    "splitter": {
        "category": "other", "label": "Flow Splitter", "kind": "Flow",
        "sumo_template": "Sumo__Plant__Splitter", "sumo_unit_class": "Splitter",
        "parameters": {"fraction": {"unit": "–", "sumo": "param__f", "desc": "Split fraction (to first outlet)"}},
    },
    "sludge_splitter": {
        # Mirrors mermaid SPLIT: divides clarifier underflow into RAS and WAS.
        "category": "separation", "label": "Sludge Splitter", "kind": "Separation",
        "sumo_template": "Sumo__Plant__SludgeSplit", "sumo_unit_class": "SludgeSplitter",
        "parameters": {
            "ras_fraction": {"unit": "–",    "sumo": "param__fRAS", "desc": "Fraction underflow → RAS"},
            "Q_RAS":        {"unit": "m³/d", "sumo": "param__QRAS", "desc": "RAS flow setpoint"},
            "Q_WAS":        {"unit": "m³/d", "sumo": "param__QWAS", "desc": "WAS flow setpoint"},
        },
    },
    "combiner": {
        "category": "other", "label": "Flow Combiner", "kind": "Flow",
        "sumo_template": "Sumo__Plant__Combiner", "sumo_unit_class": "Combiner",
        "parameters": {},
    },
}

STREAM_TYPES: list[str] = ["process_flow", "ras", "was", "recycle", "reject"]

# Logical mapping from schematic stream-type to DTT addconnection "connectionType"
STREAM_TO_DTT: dict[str, str] = {
    "process_flow": "process",
    "ras":          "return_activated_sludge",
    "was":          "waste_activated_sludge",
    "recycle":      "internal_recycle",
    "reject":       "reject_water",
}

BOUNDARY_TYPES = {"influent", "effluent", "ras_flow", "was_flow"}


def is_known_unit_type(t: str) -> bool:
    return t in UNIT_TYPES


def get_unit_def(t: str) -> dict[str, Any] | None:
    return UNIT_TYPES.get(t)
