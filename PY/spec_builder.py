"""
spec_builder.py — Group HH: the two entry points and structured editing (tools 1-3).

Three tools live here, and they exist to make ONE rule mechanical:

    STRUCTURE MAY BE INFERRED. MAGNITUDES MAY NOT.          (map Q5)

  * `compose_spec`  — the STRUCTURED BACK DOOR. Explicit fields in, schema-valid spec out.
    No inference at all: a value the caller did not supply becomes the `REQUIRED` sentinel.

  * `describe_to_spec` — the PROSE FRONT DOOR. This is where the LLM risk of the whole project
    concentrates, so it is built to be incapable of the dangerous move: it extracts STRUCTURE
    from prose (ports, phases, named species, process names) and sets **every magnitude to
    `REQUIRED`**. It cannot invent a rate constant because it never writes a number.

    That is a deliberate architecture choice, not a limitation. The calling model is free to
    propose structure; the one thing no model may do is supply a magnitude that nobody measured.
    Numbers arrive later through `edit_spec` with a provenance and a source, and rung 1 refuses
    them if the backing is missing.

  * `edit_spec` — a structured edit at a named path. **Any edit CLEARS acceptance**, because a
    spec accepted at one set of values is not accepted at another (ticket 08 open question 3,
    ticket 09's proposal). The fingerprint in `spec_review` would catch a changed value at
    emission; clearing here makes the invalidation explicit rather than incidental.

Refusals are structured return values, never exceptions (tickets 17/19).
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import spec_review

# [MEASURED] the schema declares `schema_version` as `const: 1` - an INTEGER, not a string.
# Building these tools against the real schema (rather than an assumed shape) is what exposed
# that, plus two more mismatches below and one genuine schema defect: `provenance` was
# additionalProperties:false with no slot for `accepted`, so every ACCEPTED spec was invalid.
SCHEMA_VERSION = 1
REQUIRED = "REQUIRED"

# Phase words the corpus uses, for structural inference only.
_PHASE_WORDS = {"liquid": "L", "water": "L", "aqueous": "L", "gas": "Air", "air": "Air",
                "off-gas": "Air", "offgas": "Air", "sludge": "L", "solid": "L"}
_IN_WORDS = ("influent", "inlet", "feed", "input", "incoming", "inflow")
_OUT_WORDS = ("effluent", "outlet", "output", "outgoing", "outflow", "off-gas", "offgas",
              "permeate", "underflow", "overflow")
# Species mentioned in prose. Structural only - naming a species is not claiming a quantity.
_SPECIES = re.compile(r"\b(S[A-Z][A-Za-z0-9_]*|X[A-Z][A-Za-z0-9_]*|G[A-Z][A-Za-z0-9_]*)\b")


def _coeff(value: Any = REQUIRED, provenance: str = "user-stated",
           source: str = "", unverified: bool = True) -> dict:
    """A schema `coefficient`. Defaults to the REQUIRED sentinel - never to a number."""
    return {"value": value, "provenance": provenance, "source": source,
            "unverified": bool(unverified)}


def _now() -> str:
    import datetime
    return datetime.datetime.now().replace(microsecond=0).isoformat()


def _skeleton(name: str, qualified_name: str, category: str = "Custom",
              routed_as: str = "A", authoring_tool: str = "compose_spec",
              routing_evidence: list | None = None) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "identity": {"name": name, "qualified_name": qualified_name,
                     "version": 1, "category": category, "supersedes": None},
        # routing_evidence is an ARRAY of the observations that drove the classification
        "routing": {"routed_as": routed_as, "routing_evidence": list(routing_evidence or []),
                    "routing_confirmed_by_user": False},
        "classification": {"is_composite": False,
                           "composite_evidence": {"sub_units": [], "couplings": []}},
        # the schema wants `models: [model_id]`, not a flat symbol/name pair
        "model_binding": {"models": [{"id": "MODEL", "valid": [], "invalid": []}],
                          "model_base": None},
        "ports": [],
        "parameters": [],
        "processes": [],
        "code_blocks": [],
        "provenance": {"created": _now(), "authoring_tool": authoring_tool,
                       "accepted": None},
    }


# --------------------------------------------------------------------------- #
# Tool 2 — the structured back door
# --------------------------------------------------------------------------- #

def compose_spec(fields: dict) -> dict:
    """Build a schema-valid spec from EXPLICIT fields. No inference whatsoever.

    Any magnitude the caller does not supply becomes `REQUIRED`. Supplying a number without a
    provenance is refused rather than defaulted - a default provenance would be the tool
    inventing backing for a value.
    """
    name = (fields.get("name") or "").strip()
    if not name:
        return {"ok": False, "reason": "a unit name is required"}
    qn = fields.get("qualified_name") or name
    spec = _skeleton(name, qn, fields.get("category", "Custom"),
                     fields.get("routed_as", "A"), authoring_tool="compose_spec")

    for p in fields.get("ports", []) or []:
        if not p.get("symbol") or not p.get("direction"):
            return {"ok": False, "reason": f"port {p!r} needs at least a symbol and a direction"}
        spec["ports"].append({"symbol": p["symbol"], "name": p.get("name", p["symbol"]),
                              "direction": p["direction"], "phase": p.get("phase", "L"),
                              "position": p.get("position", ""), "rule": "", "comments": ""})

    for prm in fields.get("parameters", []) or []:
        if not prm.get("symbol"):
            return {"ok": False, "reason": "every parameter needs a symbol"}
        if "value" in prm and prm.get("value") is not None and not prm.get("provenance"):
            return {"ok": False,
                    "reason": f"parameter {prm['symbol']!r} has a value but no provenance",
                    "detail": ["A magnitude without provenance is unbacked. Supply a provenance "
                               "and a source, or omit the value and let it be REQUIRED."]}
        spec["parameters"].append({
            "symbol": prm["symbol"], "name": prm.get("name", prm["symbol"]),
            "unit": prm.get("unit", ""), "decimals": prm.get("decimals", 3),
            "low_limit": prm.get("low_limit", ""), "high_limit": prm.get("high_limit", ""),
            "default": _coeff(prm.get("value", REQUIRED),
                              prm.get("provenance", "user-stated"),
                              prm.get("source", ""),
                              unverified=not prm.get("source")),
        })

    for pr in fields.get("processes", []) or []:
        if not pr.get("id") or not pr.get("rate_expression"):
            return {"ok": False, "reason": f"process {pr.get('id')!r} needs an id and a rate"}
        stoich = []
        for st in pr.get("stoichiometry", []) or []:
            stoich.append({"component": st["component"],
                           "coefficient": _coeff(st.get("coefficient", REQUIRED),
                                                 st.get("provenance", "user-stated"),
                                                 st.get("source", ""),
                                                 unverified=not st.get("source"))})
        spec["processes"].append({"id": pr["id"], "name": pr.get("name", pr["id"]),
                                  "rate_expression": pr["rate_expression"],
                                  "stoichiometry": stoich})

    for blk in fields.get("code_blocks", []) or []:
        spec["code_blocks"].append({
            "section": blk.get("section", "Hydraulics"),
            "title": blk.get("title", blk.get("section", "Code")),
            "codelocation": blk.get("codelocation", "Dynamic"),
            "lines": [{"symbol": ln["symbol"], "name": ln.get("name", ln["symbol"]),
                       "expression": ln["expression"], "unit": ln.get("unit", ""),
                       "decimals": ln.get("decimals", ""), "rule": "", "comments": ""}
                      for ln in (blk.get("lines") or []) if ln.get("symbol")],
        })

    return {"ok": True, "spec": spec, "owed": len(spec_review.collect_required(spec))}


# --------------------------------------------------------------------------- #
# Tool 1 — the prose front door
# --------------------------------------------------------------------------- #

def describe_to_spec(description: str, name: str, category: str = "Custom",
                     qualified_name: str | None = None) -> dict:
    """Turn prose into a spec SKELETON in which every magnitude is REQUIRED.

    What it infers: ports and their direction/phase, candidate species names, and process
    names. What it will NEVER infer: a number. The returned `not_inferred` list says so
    explicitly, so the caller cannot mistake silence for completeness.
    """
    if not (description or "").strip():
        return {"ok": False, "reason": "an empty description infers nothing"}
    spec = _skeleton(name, qualified_name or name, category,
                     authoring_tool=f"describe_{name}",
                     routing_evidence=["routed_as defaulted to 'A' and is UNCONFIRMED - the "
                                       "prose front door does not classify.",
                                       "rung 1 refuses a Type A that introduces state variables, "
                                       "and a Type B that introduces none."])
    text = description.lower()

    # ---- ports: direction from the word, phase from the sentence around it ----
    seen = set()
    for sentence in re.split(r"[.;\n]", description):
        low = sentence.lower()
        phase = next((v for k, v in _PHASE_WORDS.items() if k in low), "L")
        for w in _IN_WORDS:
            if w in low and ("in", w) not in seen:
                seen.add(("in", w))
                spec["ports"].append({"symbol": "inp" if len(spec["ports"]) == 0 else f"inp{len(spec['ports'])}",
                                      "name": w.capitalize(), "direction": "in", "phase": phase,
                                      "position": "", "rule": "", "comments":
                                      f"inferred from the word {w!r}"})
        for w in _OUT_WORDS:
            if w in low and ("out", w) not in seen:
                seen.add(("out", w))
                spec["ports"].append({"symbol": "outp" if not any(p["direction"] == "out" for p in spec["ports"]) else f"outp{len(spec['ports'])}",
                                      "name": w.capitalize(), "direction": "out", "phase": phase,
                                      "position": "", "rule": "", "comments":
                                      f"inferred from the word {w!r}"})
    if not any(p["direction"] == "in" for p in spec["ports"]):
        spec["ports"].append({"symbol": "inp", "name": "Influent", "direction": "in",
                              "phase": "L", "position": "", "rule": "",
                              "comments": "default inlet - no inlet word found in the prose"})
    if not any(p["direction"] == "out" for p in spec["ports"]):
        spec["ports"].append({"symbol": "outp", "name": "Effluent", "direction": "out",
                              "phase": "L", "position": "", "rule": "",
                              "comments": "default outlet - no outlet word found in the prose"})

    # ---- candidate species, structural only ----
    species = sorted(set(_SPECIES.findall(description)))

    # ---- processes: one per "oxidation/growth/decay/hydrolysis/..." mention ----
    proc_words = re.findall(r"\b(\w+\s+(?:oxidation|growth|decay|hydrolysis|reduction|"
                            r"fermentation|precipitation|adsorption|nitrification|"
                            r"denitrification))\b", text)
    for i, pw in enumerate(dict.fromkeys(proc_words), start=1):
        spec["processes"].append({
            "id": f"r{i}", "name": pw.strip().capitalize(),
            "rate_expression": REQUIRED,
            "stoichiometry": [{"component": s, "coefficient": _coeff()} for s in species[:6]],
        })

    # ---- volume is the one universally present parameter; still REQUIRED ----
    spec["parameters"].append({
        "symbol": "L.Vtrain", "name": "Volume per train", "unit": "m3", "decimals": 1,
        "low_limit": "MinV", "high_limit": "MaxV",
        "default": _coeff(),   # REQUIRED
    })

    # TICKET 19: REFUSE AND ASK, NEVER GUESS.
    # If the prose describes reactions, this is Type B by definition - the schema enforces
    # `processes: maxItems 0` for Type A. But Type B also requires a DECLARED forked model base
    # and NEW STATE VARIABLES, neither of which can be read out of prose. Silently routing to B
    # would produce a spec that fails both the schema and rung 1, so the processes are returned
    # as a PROPOSAL alongside a refusal, and the spec itself stays a valid Type A skeleton.
    proposed = spec["processes"]
    spec["processes"] = []
    refusal = None
    if proposed:
        refusal = {
            "refused": "automatic Type A/B routing",
            "why": f"the prose describes {len(proposed)} reaction process(es): "
                   + ", ".join(p["name"] for p in proposed),
            "consequence": "introducing Gujer rows is Type B by definition, and Type B "
                           "additionally requires a forked model base and new state variables "
                           "- neither is inferable from prose.",
            "ask": ["Confirm routed_as = 'B' (or correct it).",
                    "Declare the forked model base in model_binding.model_base.",
                    "Declare the new state variables the reactions act on.",
                    "Then add the processes with hh_edit_unit_spec."],
            "proposed_processes": proposed,
        }

    owed = spec_review.collect_required(spec)
    return {
        "ok": True,
        "spec": spec,
        "inferred": {
            "ports": [f"{p['symbol']} ({p['direction']}, {p['phase']})" for p in spec["ports"]],
            "species_mentioned": species,
            "processes": [p["name"] for p in proposed],
        },
        "not_inferred": [
            "EVERY magnitude. No rate constant, yield, half-saturation or volume was inferred - "
            "each is set to the REQUIRED sentinel and must be supplied with a provenance.",
            "Stoichiometric coefficients: the components are listed, the numbers are not.",
            "Whether this unit is Type A or Type B - routing.routed_as defaults to 'A' and is "
            "unconfirmed; rung 1 refuses a Type A that introduces state variables.",
        ],
        "owed": len(owed),
        "refusal": refusal,
        "next": ("Resolve the routing refusal above, then fill the REQUIRED values with "
                 "hh_edit_unit_spec." if refusal else
                 "Fill the REQUIRED values with hh_edit_unit_spec, then hh_review_unit_spec."),
    }


# --------------------------------------------------------------------------- #
# Tool 3 — structured editing
# --------------------------------------------------------------------------- #

def _resolve(spec: dict, path: str):
    """Walk a dotted/indexed path like `parameters[2].default.value`. Returns (parent, key)."""
    cur: Any = spec
    tokens = re.findall(r"[^.\[\]]+|\[\d+\]", path)
    if not tokens:
        raise KeyError("empty path")
    for tok in tokens[:-1]:
        cur = cur[int(tok[1:-1])] if tok.startswith("[") else cur[tok]
    last = tokens[-1]
    return (cur, int(last[1:-1]) if last.startswith("[") else last)


def edit_spec(spec: dict, path: str, value: Any,
              provenance: str | None = None, source: str | None = None) -> dict:
    """Set one named path. ANY edit clears acceptance.

    Setting a magnitude requires a provenance: a number with no backing is exactly what rung 1
    exists to refuse, and letting `edit_spec` write one without it would route around the guard.
    """
    try:
        parent, key = _resolve(spec, path)
        before = parent[key]
    except Exception as e:
        return {"ok": False, "reason": f"path {path!r} does not resolve: {e}"}

    # Setting a coefficient's value: demand provenance in the same call.
    if key == "value" and isinstance(parent, dict) and "provenance" in parent:
        if spec_review._as_magnitude(value) is not None and not provenance:
            return {"ok": False,
                    "reason": "setting a magnitude requires a provenance in the same call",
                    "detail": ["A number with no backing is what rung 1 refuses; writing one "
                               "here would route around the guard.",
                               "Pass provenance= and source=."]}
        parent["value"] = value
        if provenance:
            parent["provenance"] = provenance
        if source is not None:
            parent["source"] = source
            parent["unverified"] = not bool(source)
    else:
        parent[key] = value

    had_acceptance = bool(spec_review.acceptance_of(spec))
    if had_acceptance:
        spec.setdefault("provenance", {})["accepted"] = None

    v = spec_review.lint(spec)
    return {"ok": True, "path": path, "before": before, "after": value,
            "acceptance_cleared": had_acceptance,
            "note": ("acceptance was CLEARED - a spec accepted at one set of values is not "
                     "accepted at another" if had_acceptance else "spec was not accepted"),
            "lint_ok": v["ok"], "still_owed": len(v["required"])}


if __name__ == "__main__":                                   # pragma: no cover
    print(__doc__)
