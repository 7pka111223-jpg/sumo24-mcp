"""
spec_review.py — Group HH, ticket 08: the prose-to-spec review gate (rung 1).

This is the one place in the pipeline that is NOT deterministic. Everything downstream —
workbook emission, SMT, slcompiler, the tracer — is mechanical and checkable. This step is
where a plausible-looking invention can enter, so the fabrication policy (map Q5) is enforced
here or nowhere.

It does two jobs that are really one job:

  1. THE REVIEW ARTIFACT — a rendered, read-only view of a proposed unit_spec.json, ordered so
     the dangerous things are impossible to miss: the values the user still owes, then values
     that are unverified or carry weak provenance, and only then the structure.

  2. RUNG 1 LINT — the enforcement behind that view. Ticket 05 established that JSON Schema
     *cannot* enforce the REQUIRED sentinel (the field must also accept symbolic expressions
     like "-1/YOHO,VFA,ox"), so it assigned enforcement to "a rung-1 linter duty". Before this
     module no linter existed, and PY/tools/repro_required_sentinel.py demonstrated that an
     unfilled REQUIRED passed every gate in the tree.

Design decisions, each traceable to a ticket:

  - Rendered views are generated FROM the spec on demand and are read-only, so they cannot
    drift from it (ticket 08's first question). The spec stays the single source of truth.
  - The REQUIRED list is the PRIMARY output, printed first (ticket 08).
  - Acceptance is an explicit, timestamped user act, and emission refuses on an unaccepted
    spec (ticket 08 amendment: promoted from recommendation to rule).
  - Structure may be inferred from prose; MAGNITUDES MAY NOT. Every numeric magnitude must
    carry provenance, and anything the model could not source must be REQUIRED rather than
    guessed (map Q5).
  - Refusals are structured return values, never exceptions (tickets 17/19).

Read-only: this module never writes a spec unless `accept()` is called explicitly.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import re
import sys
from typing import Any, Iterator

REQUIRED_SENTINEL = "REQUIRED"

# Named limit sentinels that are legitimate non-numeric values (ticket 05).
LIMIT_SENTINELS = {"BigNumber", "MinV", "MaxV", "MaxFlow", "Zero", "One"}

# Provenance values that CLAIM a human or a citation stands behind this number.
# NOTE: a claim is not evidence. `provenance` is self-asserted by whoever wrote the spec -
# including a model - so it is a LABEL, not a guarantee. Rung 1 therefore requires
# corroboration (below) and, for emission, explicit per-value human confirmation.
STRONG_PROVENANCE = {"user-measured", "literature-cited", "inherited-model-base"}
WEAK_PROVENANCE = {"user-stated"}

# Only this one is not a human assertion: it is copied from the shipped model base.
SELF_ASSERTED = STRONG_PROVENANCE - {"inherited-model-base"} | WEAK_PROVENANCE

# Something citation-shaped: an author-year, a DOI, a URL, or a standards reference.
_CITATION = re.compile(
    r"(\b19|\b20)\d{2}\b|doi[:/]|https?://|\bISBN\b|\bIWA\b|et al\.?",
    re.IGNORECASE)

# Hedge words anywhere in the value, not as exact whole tokens: "~0.5" and "0.5 (typical)"
# both slipped past the original whole-token match.
_PROSE = re.compile(
    r"~|\bab(?:ou)?t\b|\bapprox|\broughly\b|\brough\b|\bcirca\b|\bca\.|"
    r"\baround\b|\bmaybe\b|\btypical|\btyp\)|\bballpark\b|\border of\b|"
    r"\bsomewhere\b|ish\b|estimat|\bguesstimat|\bnominal\b|\bor so\b|"
    r"give or take|\bnear\b|\bsome\b",
    re.IGNORECASE)


# --------------------------------------------------------------------------- #
# Traversal
# --------------------------------------------------------------------------- #

def _walk(node: Any, path: str = "") -> Iterator[tuple[str, Any]]:
    """Yield (json_path, node) for every dict/list node in the spec."""
    yield path or "$", node
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _walk(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk(v, f"{path}[{i}]")


def _is_coefficient(node: Any) -> bool:
    """The schema's `coefficient` shape: an object carrying `value` + `provenance`."""
    return isinstance(node, dict) and "value" in node and "provenance" in node


def iter_values(spec: dict) -> Iterator[tuple[str, dict]]:
    """Every coefficient-shaped node in the spec, with its JSON path."""
    for path, node in _walk(spec):
        if _is_coefficient(node):
            yield path, node


# --------------------------------------------------------------------------- #
# Rung 1 checks
# --------------------------------------------------------------------------- #

def _as_magnitude(v):
    """Return a float if `v` is a magnitude, else None.

    A magnitude may arrive STRING-TYPED (`"999"`). Both corroboration and confirmation were
    numeric-only, so a string-typed number skipped every check and reached emission with zero
    backing (found by adversarial review, probe P3c). Symbolic expressions and sentinels are
    not magnitudes and are handled elsewhere.
    """
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        t = v.strip()
        if t in LIMIT_SENTINELS or t == REQUIRED_SENTINEL:
            return None
        try:
            return float(t)
        except ValueError:
            return None
    return None


def collect_required(spec: dict) -> list[dict]:
    """Every value still sitting at the REQUIRED sentinel. THE primary output."""
    out = []
    for path, node in iter_values(spec):
        if node.get("value") == REQUIRED_SENTINEL:
            out.append({"path": path,
                        "what": _describe(spec, path),
                        "unit": node.get("unit", ""),
                        "source": node.get("source", "")})
    return out


def collect_weak(spec: dict) -> list[dict]:
    """Values that will reach a simulation but nobody has stood behind."""
    out = []
    for path, node in iter_values(spec):
        v = node.get("value")
        if v == REQUIRED_SENTINEL:
            continue                      # already in the REQUIRED list
        prov = node.get("provenance")
        unver = bool(node.get("unverified"))
        if unver or prov in WEAK_PROVENANCE or prov not in (STRONG_PROVENANCE | WEAK_PROVENANCE):
            out.append({"path": path, "what": _describe(spec, path), "value": v,
                        "provenance": prov, "unverified": unver,
                        "source": node.get("source", "")})
    return out


def collect_unparseable(spec: dict) -> list[dict]:
    """Values that are neither a number, a known limit sentinel, nor a symbolic expression.

    This is the check that catches `"about 0.5"` — which the schema accepts, because `value`
    must also accept expressions like `-1/YOHO,VFA,ox`.
    """
    out = []
    for path, node in iter_values(spec):
        v = node.get("value")
        if isinstance(v, (int, float)) or v == REQUIRED_SENTINEL or v in LIMIT_SENTINELS:
            continue
        if not isinstance(v, str):
            out.append({"path": path, "value": v, "why": "not a number, sentinel or expression"})
            continue
        # A symbolic expression is made of symbol chars and operators. Prose is not.
        # Substring/regex, NOT whole-token: "~0.5" and "0.5 (typical)" are hedges too.
        if _PROSE.search(v):
            out.append({"path": path, "value": v, "why": "reads as a hedge, not an exact value"})
    return out


def collect_routing_faults(spec: dict) -> list[dict]:
    """H3: the routing/composite checks tickets 19 and 17 asserted the linter performs.

    Ticket 19: "the linter enforces consistency, so routing cannot drift from content."
    Ticket 17: composites are out of cycle 1 and must be DETECTED AND REFUSED, naming the
    sub-units found - as a structured refusal, not an exception.
    Neither existed in code until now; `routed_as` was only rendered.
    """
    out = []
    routing = spec.get("routing") or {}
    routed_as = routing.get("routed_as")
    intro = ((spec.get("state_variables") or {}).get("introduced")) or []
    classification = spec.get("classification") or {}

    # 19 - routing must match content, both ways.
    if routed_as == "A" and intro:
        out.append({"kind": "routing-drift", "refusal": True,
                    "why": f"routed_as 'A' but the spec introduces {len(intro)} new state "
                           f"variable(s) ({', '.join(sv.get('symbol','?') for sv in intro)}). "
                           f"Introducing state variables is Type B by definition.",
                    "ask": "Confirm the routing, or remove the new state variables."})
    if routed_as == "B" and not intro:
        out.append({"kind": "routing-drift", "refusal": True,
                    "why": "routed_as 'B' but the spec introduces no new state variables. "
                           "Type B exists to add state variables to a forked model base.",
                    "ask": "Confirm the routing, or declare the new state variables."})
    if routed_as not in ("A", "B"):
        out.append({"kind": "routing-missing", "refusal": True,
                    "why": f"routing.routed_as is {routed_as!r}; it must be 'A' or 'B'.",
                    "ask": "Classify the unit. Never guess (ticket 19: refuse and ask)."})

    # 17 - composites are out of cycle 1: detect and refuse, naming what was found.
    if classification.get("is_composite"):
        subs = ((classification.get("composite_evidence") or {}).get("sub_units")) or []
        out.append({"kind": "composite-refused", "refusal": True,
                    "why": "this unit is composite; composite authoring is out of cycle 1.",
                    "sub_units": subs,
                    "ask": "Author each sub-unit separately: "
                           + (", ".join(str(x) for x in subs) if subs else "(none named)")})
    return out


def _value_fingerprint(node: dict) -> str:
    """Stable hash of the value + its provenance claim, so confirmation cannot survive an edit."""
    # `unit` is included deliberately: the substance basis lives there (g COD.m-3 vs g S.m-3),
    # so a post-acceptance basis swap must revoke confirmation too.
    payload = json.dumps({"v": node.get("value"), "p": node.get("provenance"),
                          "s": node.get("source", ""), "u": node.get("unit", "")},
                         sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def collect_uncorroborated(spec: dict) -> list[dict]:
    """Magnitudes whose provenance CLAIM carries nothing to back it up.

    `provenance` is written by whoever authored the spec - possibly a model - so on its own it
    is a label, not evidence. The cheapest fabrication is the string "user-measured" with an
    empty source. Rung 1 cannot verify a citation is real, but it CAN refuse a bare claim.
    """
    out = []
    for path, node in iter_values(spec):
        v = _as_magnitude(node.get("value"))
        if v is None:
            continue                                   # symbolic/sentinel handled elsewhere
        prov = node.get("provenance")
        if prov not in SELF_ASSERTED:
            continue                                   # inherited-model-base needs no source
        src = (node.get("source") or "").strip()
        why = None
        if not src:
            why = f"provenance '{prov}' asserted with no source at all"
        elif len(src) < 12:
            why = f"provenance '{prov}' with a source too short to corroborate ({src!r})"
        elif prov == "literature-cited" and not _CITATION.search(src):
            why = ("provenance 'literature-cited' but the source contains nothing "
                   "citation-shaped (no author-year, DOI, URL or standard)")
        if why:
            out.append({"path": path, "what": _describe(spec, path), "value": v,
                        "provenance": prov, "source": src, "why": why})
    return out


def collect_unconfirmed(spec: dict) -> list[dict]:
    """Magnitudes a human has not explicitly confirmed at acceptance time.

    This is the guard that a fabricating model cannot satisfy by itself: confirmation is
    recorded when a person accepts the spec, keyed to a fingerprint of the value. Change the
    value afterwards and the fingerprint no longer matches, so the confirmation lapses.
    """
    confirmed = ((spec.get("provenance") or {}).get("accepted") or {}).get("confirmed") or {}
    out = []
    for path, node in iter_values(spec):
        v = _as_magnitude(node.get("value"))
        if v is None:
            continue
        if node.get("provenance") == "inherited-model-base":
            continue
        if confirmed.get(path) != _value_fingerprint(node):
            out.append({"path": path, "what": _describe(spec, path), "value": v,
                        "provenance": node.get("provenance")})
    return out


def lint(spec: dict) -> dict:
    """Rung 1. Returns a structured verdict; never raises, never exits."""
    required = collect_required(spec)
    weak = collect_weak(spec)
    unparseable = collect_unparseable(spec)
    uncorroborated = collect_uncorroborated(spec)
    routing = collect_routing_faults(spec)
    errors = []
    if required:
        errors.append(f"{len(required)} value(s) still at the REQUIRED sentinel")
    if unparseable:
        errors.append(f"{len(unparseable)} value(s) are neither number, sentinel nor expression")
    if uncorroborated:
        errors.append(f"{len(uncorroborated)} magnitude(s) claim provenance with nothing to back it")
    if routing:
        errors.append(f"{len(routing)} routing/composite fault(s)")
    return {
        "ok": not errors,
        "errors": errors,
        "required": required,
        "unparseable": unparseable,
        "uncorroborated": uncorroborated,
        "routing": routing,
        "unconfirmed": collect_unconfirmed(spec),
        "weak_provenance": weak,
        "accepted": acceptance_of(spec),
    }


# --------------------------------------------------------------------------- #
# Acceptance (ticket 08 amendment: a RULE, not a recommendation)
# --------------------------------------------------------------------------- #

def acceptance_of(spec: dict) -> dict | None:
    return (spec.get("provenance") or {}).get("accepted")


def spec_fingerprint(spec: dict) -> str:
    """Bind approval to all specification content, excluding the approval itself."""
    content = dict(spec)
    content["provenance"] = dict(content.get("provenance") or {})
    content["provenance"].pop("accepted", None)
    return hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def may_emit(spec: dict, allow_bulk: bool = False) -> dict:
    """The gate the workbook generator must call. Structured refusal, never an exception."""
    v = lint(spec)
    if not v["ok"]:
        return {"may_emit": False, "reason": "rung-1 lint failed", "detail": v["errors"]}
    if not acceptance_of(spec):
        return {"may_emit": False, "reason": "spec has not been explicitly accepted",
                "detail": ["Acceptance is an explicit, timestamped user act (ticket 08). "
                           "Emission refuses on an unaccepted spec."]}
    if acceptance_of(spec).get("spec_sha256") != spec_fingerprint(spec):
        return {"may_emit": False, "reason": "executable specification changed or legacy approval lacks whole-spec hash",
                "detail": ["Review and explicitly accept the complete current specification again."]}
    stale = collect_unconfirmed(spec)
    if stale:
        return {"may_emit": False,
                "reason": f"{len(stale)} magnitude(s) unconfirmed or changed since acceptance",
                "detail": [f"{x['what']} = {x['value']}" for x in stale[:10]]}
    # Bulk confirmation must COST something, or recording it is cosmetic. It confirms every
    # magnitude in one call without the confirmer having seen them individually, so it is a
    # weaker state and emission requires an explicit opt-in to proceed on it.
    if acceptance_of(spec).get("confirmation") == "bulk" and not allow_bulk:
        return {"may_emit": False,
                "reason": "spec was accepted with BULK confirmation",
                "detail": ["Every magnitude was confirmed in a single call rather than reviewed "
                           "individually. Re-accept with per-value confirmation, or pass "
                           "allow_bulk=True to proceed deliberately."]}
    return {"may_emit": True, "reason": "lint clean, spec accepted, magnitudes confirmed",
            "detail": [f"accepted by {acceptance_of(spec).get('by')} "
                       f"at {acceptance_of(spec).get('at')}"]}


def accept(spec: dict, by: str, confirm: "list[str] | None" = None,
           confirm_all: bool = False) -> dict:
    """Record explicit acceptance WITH per-value human confirmation.

    `provenance` is self-asserted and cannot be the guard on its own (a fabricating model writes
    "user-measured" as cheaply as anything else).

    **WHAT THIS IS AND IS NOT.** [MEASURED by adversarial review] This is a PROTOCOL, not an
    authentication boundary. `by` is an unauthenticated free-text string, this module can be
    called by the same agent that wrote the spec, and `provenance.accepted` is plain JSON that
    anything able to write the spec can forge. A model CAN complete this protocol by itself.
    An earlier version of this docstring claimed otherwise; that claim was false and is retracted.

    What it does buy, and this is real: every magnitude is enumerated and must be named at
    acceptance; the choice is recorded (`per-value` vs `bulk`) and is visible afterwards; and a
    fingerprint over value+provenance+source+unit means any later edit REVOKES emission. It makes
    unbacked numbers *conspicuous and attributable*, not impossible.

    `confirm` is the list of value paths being confirmed. `confirm_all=True` confirms every
    outstanding magnitude and is RECORDED AS BULK so it is visible in the spec afterwards.
    """
    v = lint(spec)
    if not v["ok"]:
        return {"accepted": False, "reason": "cannot accept a spec that fails rung 1",
                "detail": v["errors"]}

    outstanding = {u["path"] for u in collect_unconfirmed(spec)}
    chosen = set(confirm or []) | (outstanding if confirm_all else set())
    missing = sorted(outstanding - chosen)
    if missing:
        return {"accepted": False,
                "reason": f"{len(missing)} magnitude(s) not confirmed by a human",
                "detail": missing[:20],
                "hint": "pass confirm=[paths] or confirm_all=True; provenance alone is a "
                        "self-assertion and is not accepted as backing"}

    by_path = {path: node for path, node in iter_values(spec)}
    # [MEASURED 2026-09-07] confirm_all on a fully-confirmed spec used to REPLACE the
    # record with an empty stamp set (chosen == {} when nothing is outstanding), wiping a
    # perfectly good acceptance and making every magnitude stale. Stamps must UNION with
    # the existing record, and previous stamps are kept VERBATIM: a stamp reflects the
    # value at its acceptance time, so if the value changed since, the mismatch with the
    # current node is exactly what collect_unconfirmed must keep reporting.
    previous = ((spec.get("provenance") or {}).get("accepted") or {}).get("confirmed") or {}
    spec.setdefault("provenance", {})["accepted"] = {
        "by": by,
        "at": datetime.datetime.now().replace(microsecond=0).isoformat(),
        "lint": "clean",
        "confirmation": "bulk" if confirm_all else "per-value",
        "confirmed": {**previous,
                      **{p: _value_fingerprint(by_path[p]) for p in sorted(chosen) if p in by_path}},
        "spec_sha256": spec_fingerprint(spec),
    }
    return {"accepted": True, "reason": "recorded", "detail": [spec["provenance"]["accepted"]]}


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #

def _describe(spec: dict, path: str) -> str:
    """Human label for a coefficient path — the engineer should not read JSON paths."""
    parts = path.split(".")
    try:
        if "parameters[" in path:
            i = int(path.split("parameters[")[1].split("]")[0])
            p = spec["parameters"][i]
            return f"parameter {p.get('symbol','?')} - {p.get('name','')}"
        if "state_variables" in path and "introduced[" in path:
            i = int(path.split("introduced[")[1].split("]")[0])
            sv = spec["state_variables"]["introduced"][i]
            return f"state variable {sv.get('symbol','?')} - {sv.get('name','')}"
        if "processes[" in path:
            i = int(path.split("processes[")[1].split("]")[0])
            pr = spec["processes"][i]
            if "stoichiometry[" in path:
                j = int(path.split("stoichiometry[")[1].split("]")[0])
                comp = pr["stoichiometry"][j].get("component", "?")
                return f"process {pr.get('id','?')} - stoichiometry for {comp}"
            return f"process {pr.get('id','?')} - {pr.get('name','')}"
    except Exception:
        pass
    return parts[-1] if parts else path


def _rule(ch: str = "-", n: int = 78) -> str:
    return ch * n


def render(spec: dict) -> str:
    """The review artifact. Ordered by danger, not by document structure."""
    L: list[str] = []
    ident = spec.get("identity", {})
    v = lint(spec)

    L.append(_rule("="))
    L.append(f"UNIT SPEC REVIEW - {ident.get('qualified_name', ident.get('name','(unnamed)'))}"
             f"  v{ident.get('version','?')}")
    L.append(f"category: {ident.get('category','?')}    "
             f"type: {(spec.get('routing') or {}).get('routed_as','?')}    "
             f"composite: {(spec.get('classification') or {}).get('is_composite','?')}")
    L.append(_rule("="))
    L.append("")

    # 1. THE VALUES YOU STILL OWE — first, always.
    L.append("1. VALUES YOU STILL OWE  (nothing can be built until these are filled)")
    L.append(_rule())
    if v["required"]:
        for r in v["required"]:
            L.append(f"  [ ] {r['what']}")
            L.append(f"        path : {r['path']}")
            if r["unit"]:
                L.append(f"        unit : {r['unit']}")
            if r["source"]:
                L.append(f"        note : {r['source']}")
    else:
        L.append("  (none — every value is filled)")
    L.append("")

    # 2. Values that will reach a simulation with weak backing.
    L.append("2. VALUES NOBODY HAS STOOD BEHIND  (filled, but unverified or self-asserted)")
    L.append(_rule())
    if v["weak_provenance"]:
        for w in v["weak_provenance"]:
            flag = "UNVERIFIED" if w["unverified"] else str(w["provenance"])
            L.append(f"  ! {w['what']} = {w['value']}   [{flag}]")
            if w["source"]:
                L.append(f"        source: {w['source']}")
    else:
        L.append("  (none)")
    L.append("")

    # 3. Values that are not numbers at all.
    if v["unparseable"]:
        L.append("3. VALUES THAT ARE NOT NUMBERS  (schema accepts these; rung 1 does not)")
        L.append(_rule())
        for u in v["unparseable"]:
            L.append(f"  X {u['path']} = {u['value']!r}   ({u['why']})")
        L.append("")

    # 4. Ports.
    L.append("4. PORTS")
    L.append(_rule())
    for p in spec.get("ports", []) or []:
        L.append(f"  {p.get('direction','?'):3s}  {p.get('symbol','?'):6s} {p.get('name','?'):14s} phase={p.get('phase','')}")
    L.append("")

    # 5. State variables introduced.
    intro = ((spec.get("state_variables") or {}).get("introduced")) or []
    if intro:
        L.append("5. NEW STATE VARIABLES  (each needs formula AND declared composition)")
        L.append(_rule())
        for sv in intro:
            f = sv.get("formula", {})
            el = "".join(f"{k}{v_}" for k, v_ in (f.get("elements") or {}).items())
            comp = sv.get("composition", {})
            L.append(f"  {sv.get('symbol','?'):8s} {sv.get('name',''):34s} {sv.get('unit','')}")
            L.append(f"        formula     : {el}   charge {f.get('charge','?')}")
            L.append(f"        composition : basis={comp.get('basis','MISSING')} "
                     f"{comp.get('values','')}")
        L.append("")

    # 6. Processes and rates.
    procs = spec.get("processes", []) or []
    if procs:
        L.append("6. PROCESSES - rates")
        L.append(_rule())
        for pr in procs:
            L.append(f"  {pr.get('id','?')}: {pr.get('name','')}")
            L.append(f"        rate = {pr.get('rate_expression','?')}")
        L.append("")

        # 7. Gujer matrix.
        comps: list[str] = []
        for pr in procs:
            for st in pr.get("stoichiometry", []) or []:
                if st.get("component") not in comps:
                    comps.append(st.get("component"))
        if comps:
            L.append("7. STOICHIOMETRIC (GUJER) MATRIX")
            L.append(_rule())
            rows = []
            for pr in procs:
                rows.append({st.get("component"): str(st.get("coefficient", {}).get("value", ""))
                             for st in pr.get("stoichiometry", []) or []})
            # column width must fit the widest CELL, not just the header, or symbolic
            # coefficients like -(1 - Y_SOB)/Y_SOB run into the next column unreadably.
            widths = {c: max(len(c), max((len(r.get(c, "")) for r in rows), default=0)) + 2
                      for c in comps}
            L.append("  " + "process".ljust(8) + "".join(c.rjust(widths[c]) for c in comps))
            for pr, row in zip(procs, rows):
                cells = "".join(row.get(c, ".").rjust(widths[c]) for c in comps)
                L.append("  " + str(pr.get("id", "?")).ljust(8) + cells)
            L.append("")
            L.append("  ('.' = component does not participate in that process)")
            L.append("")

    # 8. Verdict and what to do next.
    L.append("8. GATE")
    L.append(_rule())
    g = may_emit(spec)
    L.append(f"  rung-1 lint : {'PASS' if v['ok'] else 'FAIL - ' + '; '.join(v['errors'])}")
    acc = acceptance_of(spec)
    L.append(f"  accepted    : {'yes, by ' + str(acc.get('by')) + ' at ' + str(acc.get('at')) if acc else 'NO'}")
    L.append(f"  may emit    : {'YES' if g['may_emit'] else 'NO - ' + g['reason']}")
    L.append("")
    L.append("  To correct a value:  spec_review.py --set <path> <value> --provenance <p> --source <s>")
    L.append("  To accept:           spec_review.py --accept <your name>")
    L.append("  Re-prompting the model is NOT offered here: it can silently revise parts you did")
    L.append("  not mention. Corrections are structured edits against named paths (ticket 08).")
    L.append(_rule("="))
    return "\n".join(L)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        print("usage: spec_review.py <spec.json> [--lint | --render | --accept <name>]")
        return 2
    path = argv[1]
    mode = argv[2] if len(argv) > 2 else "--render"
    with open(path, encoding="utf-8") as fh:
        spec = json.load(fh)

    if mode == "--lint":
        v = lint(spec)
        print(json.dumps({k: v[k] for k in ("ok", "errors")}, indent=2))
        print(f"required: {len(v['required'])}   weak: {len(v['weak_provenance'])}   "
              f"unparseable: {len(v['unparseable'])}")
        return 0 if v["ok"] else 1
    if mode == "--accept":
        who = argv[3] if len(argv) > 3 else "unknown"
        r = accept(spec, who)
        if r["accepted"]:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(spec, fh, indent=2, ensure_ascii=False)
        print(json.dumps(r, indent=2, default=str))
        return 0 if r["accepted"] else 1
    print(render(spec))
    return 0 if lint(spec)["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
