"""
tracer_test.py — Group HH, ticket 12 Phase E: rung 5, the runtime verification rung.

Two halves:

  **5a — conservative tracer.** With every reaction rate zeroed, a unit must conserve: what
  flows in flows out, component by component. This tests the *plumbing* — ports, volume, flow
  routing — independently of any biology.

  **5b — degenerate equivalence.** A REACTIVE model with its rates zeroed must reach the same
  steady state as the equivalent NON-REACTIVE model. This is the check that catches a unit whose
  Gujer matrix is wired to the wrong components: 5a passes on the plumbing, and only 5b notices
  that the chemistry is attached wrongly.

THE RULES, each measured:

  * **`schedule()` is a liar.** [MEASURED] It returns a normal job id and raises nothing when the
    model fails to load. The real success signal is a **non-zero ROW COUNT** plus the message
    callback content. Nothing here trusts the returned id.

  * **Times are in MILLISECONDS.** [MEASURED] `set Sumo__StopTime 0.05` is rejected with
    `Value is not valid` and the run then ends instantly, producing rows that look like a
    completed simulation. Use `DAY`/`HOUR` below.

  * **Compare components by NAME, never by index.** Ports carry different component sets, and
    ticket 03b/04 disagree on column counts (102 vs 88). An index-keyed comparison silently
    compares unrelated species.

  * **Zeroing rates is not enough on its own.** [MEASURED, ticket 07] The aeration source
    parameters (`Qair_NTP`, `SSOTE0`, `SSOTEasym`) must be zeroed too, or the aer-branch of the
    gas-transfer block injects oxygen and drives the model to the `99999.9` sentinel even with
    `kL_GO2_bub = 0`.

  * **`-nosort` builds cannot be used here.** [MEASURED] Their algebraic layer never evaluates,
    so derived variables stay at `99999.9` and every conservation check is meaningless. Rung 5
    refuses a model whose derived variables are frozen — see `_sentinel_guard`.
"""
from __future__ import annotations

import pathlib
import re
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

DAY = 86400000        # SUMO times are in MILLISECONDS
HOUR = 3600000
SENTINEL = 99999.9

# Every r_j expression factors through one of these (ticket 07, verified against the XML).
ZERO_PREFIXES = ("mu", "b", "q", "kORPswitch", "kL_GO2_bub", "kL_GO2_sur")
# Aeration/O2 sources that must be zeroed or the model keeps injecting oxygen.
# Names DIFFER BY UNIT: `Simple CSTR` has `Qair_NTP`; `CSTR with diffused aeration and
# calculated DO` has `MaxflowQair_NTP`/`MinfluxQair_NTP` plus a DO controller (`DOSP`) that
# holds SO2 at its setpoint. Ticket 07's list was Simple-CSTR-only and silently matched
# nothing here, so oxygen kept entering and SO2 was the worst offender by 13 orders of
# magnitude. `zero_rate_commands` now REPORTS which of these were absent instead of
# quietly skipping them.
AERATION_ZEROS = ["Sumo__Plant__CSTR__param__Qair_NTP",
                  "Sumo__Plant__CSTR__param__SSOTE0",
                  "Sumo__Plant__CSTR__param__SSOTEasym",
                  "Sumo__Plant__CSTR__param__MaxflowQair_NTP",
                  "Sumo__Plant__CSTR__param__MinfluxQair_NTP",
                  "Sumo__Plant__CSTR__param__DOSP",
                  "Sumo__Plant__CSTR__param__GO2_air_inp",
                  "Sumo__Plant__CSTR__param__GO2_aer",
                  "Sumo__Plant__CSTR__param__GO2_nonaer"]


def _xml_text(xml_path) -> str:
    return pathlib.Path(xml_path).read_text(encoding="utf-8", errors="replace")


def zero_rate_commands(xml_path, model_prefix: str = "Sumo2C") -> tuple[list[str], dict]:
    """DTT `set` commands zeroing every rate-driving parameter, plus the aeration sources."""
    d = _xml_text(xml_path)
    pat = r'cname="(Sumo__Plant__param__%s__[A-Za-z0-9_]+)"[^>]*role="Parameter"' % model_prefix
    params = set(re.findall(pat, d))
    zero = sorted(p for p in params if p.split("__")[-1].startswith(ZERO_PREFIXES))
    aeration = [p for p in AERATION_ZEROS if p in d]
    missing = [p for p in AERATION_ZEROS if p not in d]
    targets = zero + aeration
    return ([f"set {p} 0" for p in targets],
            {"zeroed": [p.split("__")[-1] for p in targets],
             "aeration_matched": [p.split("__")[-1] for p in aeration],
             "aeration_absent": [p.split("__")[-1] for p in missing],
             "n_rate_params": len(zero)})


def port_flux_map(xml_path, port_prefix: str) -> dict[str, str]:
    """`{component: full flux variable}` for a port. Keyed by NAME, never by position."""
    d = _xml_text(xml_path)
    comps = set(re.findall(r"Sumo__Plant__" + port_prefix + r"__F_([A-Za-z0-9_]+)", d))
    return {c: f"Sumo__Plant__{port_prefix}__F_{c}" for c in comps}


def state_variable_roles(xml_path, unit_prefix: str = "CSTR") -> dict[str, str]:
    """`{component: role}` from the XML. The role decides whether it is conserved AT ALL.

    [MEASURED] `SO2` is declared `role="SystemState"` - a SET/derived quantity held at its
    setpoint - while genuinely conserved species (`SVFA`, `XSTO`, `XB_e`) are
    `role="StateVariable"`. Asserting conservation on a SystemState is asserting the wrong
    thing: it is not conserved BY DESIGN. Derived totals that carry an O2 credit (`TCOD_Th`)
    inherit the same exemption, because they differ by exactly the SystemState's flux.
    """
    d = _xml_text(xml_path)
    out = {}
    for m in re.finditer(r'<variable cname="Sumo__Plant__%s__([A-Za-z0-9_]+)"[^>]*role="([A-Za-z]+)"'
                         % unit_prefix, d):
        name, role = m.group(1), m.group(2)
        if "__" not in name:
            out[name] = role
    return out


def _sentinel_guard(row: dict) -> list[str]:
    """Derived variables frozen at 99999.9 mean the algebraic layer never evaluated."""
    return [k for k, v in row.items()
            if isinstance(v, (int, float)) and abs(float(v) - SENTINEL) < 0.5]


def run_model(model_dll, variables: list[str], commands: list[str],
              timeout_s: int = 300) -> dict:
    """Drive one DTT run. Returns rows + messages; NEVER treats the job id as success."""
    try:
        import dynamita.scheduler as ds
    except ImportError as e:
        return {"ok": False, "stage": "import", "reason": f"DTT unavailable: {e}",
                "detail": ["The DTT is never importable in CI; rung 5 is unavailable offline."]}

    if not pathlib.Path(model_dll).is_file():
        return {"ok": False, "stage": "preflight", "reason": f"model not found: {model_dll}"}

    from sumo_runtime import get_runtime
    runtime = get_runtime(ds.sumo)
    try:
        jid = runtime.schedule(str(model_dll), commands, variables, kind="tracer")
    except Exception as e:
        return {"ok": False, "stage": "schedule", "reason": f"schedule raised: {e!r}"[:200]}
    info = runtime.wait(jid, timeout_s)
    rows, msgs = info["rows"], info["messages"]
    ended = info["ended"]

    load_fail = any("Failed to load model" in m for m in msgs)
    lic_fail = any("License" in m or "licence" in m.lower() for m in msgs)
    rejected = [m for m in msgs if "not valid" in m or "failed" in m.lower()]

    # THE TRAP: a job id proves nothing. Rows + callback content are the evidence.
    if not rows or load_fail or lic_fail or not ended or rejected or info["status"] != "finished":
        return {"ok": False, "stage": "run", "job_id": jid,
                "reason": ("model failed to load" if load_fail else
                           "licence failure" if lic_fail else
                           "no data rows returned" if not rows else
                           "simulation did not report an end"),
                "rows": len(rows), "ended": ended, "rejected": rejected[:4],
                "last_msgs": msgs[-6:]}
    return {"ok": True, "stage": "run", "job_id": jid, "rows": len(rows),
            "ended": ended, "rejected": rejected[:4], "last": rows[-1], "all_rows": rows}


def rung5a_conservative_tracer(model_dll, xml_path, q: float = 24000.0,
                               influent: dict | None = None,
                               in_port: str = "Inflpipe", out_port: str = "CSTRoutp",
                               horizon_days: float = 20.0, tol: float = 1e-6,
                               timeout_s: int = 300) -> dict:
    """5a: with rates zeroed, every shared component's flux must be conserved in == out."""
    influent = influent or {"SVFA": 100.0, "SNHx": 30.0}
    zero_cmds, zinfo = zero_rate_commands(xml_path)
    inmap, outmap = port_flux_map(xml_path, in_port), port_flux_map(xml_path, out_port)
    shared = sorted(set(inmap) & set(outmap))
    if not shared:
        return {"ok": False, "stage": "setup",
                "reason": f"no shared components between {in_port} and {out_port}"}

    d = _xml_text(xml_path)
    cmds = list(zero_cmds)
    cmds.append(f"set Sumo__Plant__Influent__param__Q {q}")
    for short, val in influent.items():
        full = f"Sumo__Plant__Influent__param__{short}"
        if full in d:
            cmds.append(f"set {full} {val}")
    cmds += [f"set Sumo__StopTime {int(horizon_days * DAY)}",
             f"set Sumo__DataComm {int(0.5 * HOUR)}",
             "mode dynamic", "start"]

    variables = (["Sumo__Time", f"Sumo__Plant__{in_port}__Q", f"Sumo__Plant__{out_port}__Q"]
                 + [inmap[c] for c in shared] + [outmap[c] for c in shared])

    r = run_model(model_dll, variables, cmds, timeout_s=timeout_s)
    if not r["ok"]:
        return {"ok": False, "rung": "5a", **r}

    last = r["last"]
    frozen = _sentinel_guard(last)
    if frozen:
        return {"ok": False, "rung": "5a", "stage": "sentinel",
                "reason": "derived variables are frozen at the 99999.9 sentinel",
                "detail": ["The algebraic layer never evaluated - this is a -nosort build. "
                           "Rebuild WITHOUT -nosort; conservation cannot be judged here."],
                "frozen": frozen[:8], "rows": r["rows"]}

    q_in = last.get(f"Sumo__Plant__{in_port}__Q")
    q_out = last.get(f"Sumo__Plant__{out_port}__Q")
    roles = state_variable_roles(xml_path, unit_prefix=out_port.replace("outp", ""))
    # An absolute floor keyed to the stream scale. A "relative error" computed against a
    # 2.4e-36 denominator is undefined, not a finding: XB_e and XSTO reported 1e+06-scale
    # relative errors on values that are numerically zero.
    magnitudes = [abs(v) for v in (last.get(inmap[c]) for c in shared) if isinstance(v, (int, float))]
    scale = max(magnitudes) if magnitudes else 1.0
    abs_floor = max(scale * 1e-12, 1e-12)

    per_comp, worst, worst_comp = [], 0.0, None
    for c in shared:
        fi, fo = last.get(inmap[c]), last.get(outmap[c])
        if fi is None or fo is None:
            per_comp.append({"component": c, "status": "missing"})
            continue
        role = roles.get(c)
        if role and role != "StateVariable":
            per_comp.append({"component": c, "in": fi, "out": fo, "role": role,
                             "status": "not-conserved-by-design"})
            continue
        if abs(fi) < abs_floor and abs(fo) < abs_floor:
            per_comp.append({"component": c, "in": fi, "out": fo,
                             "status": "zero-both-sides"})
            continue
        rel = abs(fi - fo) / max(abs(fi), abs(fo), abs_floor)
        if rel > worst:
            worst, worst_comp = rel, c
        per_comp.append({"component": c, "in": fi, "out": fo, "rel": rel,
                         "status": "ok" if rel <= tol else "IMBALANCE"})
    bad = [p for p in per_comp if p.get("status") == "IMBALANCE"]
    exempt = [p for p in per_comp if p.get("status") == "not-conserved-by-design"]
    zeros = [p for p in per_comp if p.get("status") == "zero-both-sides"]
    q_rel = (abs(q_in - q_out) / max(abs(q_in), 1e-9)) if q_in is not None and q_out is not None else None

    return {"ok": not bad and (q_rel is not None and q_rel <= tol),
            "rung": "5a", "stage": "complete", "rows": r["rows"],
            # outlet flux per component, keyed by NAME - what 5b compares between models
            "outlet": {c: last.get(outmap[c]) for c in shared if last.get(outmap[c]) is not None},
            "reason": ("conserved: all shared component fluxes and flow match"
                       if not bad else f"{len(bad)} component flux imbalance(s)"),
            "n_components": len(shared), "n_imbalances": len(bad),
            "n_exempt_by_design": len(exempt), "n_zero_both_sides": len(zeros),
            "exempt": [(p["component"], p.get("role")) for p in exempt][:8],
            "q_in": q_in, "q_out": q_out, "q_rel": q_rel,
            "worst_component": worst_comp, "worst_rel": worst,
            "rates_zeroed": zinfo["n_rate_params"],
            "aeration_matched": zinfo["aeration_matched"],
            "aeration_absent": zinfo["aeration_absent"],
            "imbalances": bad[:8]}


def rung5b_degenerate_equivalence(reactive_dll, reactive_xml,
                                  nonreactive_dll, nonreactive_xml,
                                  q: float = 24000.0, influent: dict | None = None,
                                  horizon_days: float = 20.0, tol: float = 1e-4,
                                  timeout_s: int = 300) -> dict:
    """5b: a REACTIVE model with rates zeroed must match the NON-REACTIVE model's steady state.

    This is the half that catches a Gujer matrix wired to the wrong components: 5a passes on
    the plumbing regardless, because with rates zeroed the chemistry never fires.
    """
    a = rung5a_conservative_tracer(reactive_dll, reactive_xml, q=q, influent=influent,
                                   horizon_days=horizon_days, timeout_s=timeout_s)
    b = rung5a_conservative_tracer(nonreactive_dll, nonreactive_xml, q=q, influent=influent,
                                   horizon_days=horizon_days, timeout_s=timeout_s)
    if not a["ok"] or not b["ok"]:
        return {"ok": False, "rung": "5b", "stage": "prerequisite",
                "reason": "both models must pass 5a before equivalence can be judged",
                "reactive": {k: a.get(k) for k in ("ok", "reason", "rows")},
                "nonreactive": {k: b.get(k) for k in ("ok", "reason", "rows")}}

    # Compare the OUTLET flux of every component both models carry, keyed by NAME - and
    # apply the SAME role exemption 5a uses. [MEASURED] Both `SO2` and `TCOD_Th` are
    # role="SystemState": SO2 is set-handled, and TCOD_Th differs by exactly SO2's flux
    # because it carries an O2 credit. Comparing them across two models whose aeration
    # parameters differ measures the zeroing asymmetry, not the chemistry.
    # [MEASURED] A component's ROLE can DIFFER between the two models: the reactive model
    # INTEGRATES SO2 (StateVariable) while the non-reactive model SETS it (SystemState).
    # Comparing those is comparing an integrated quantity against a held one. Equivalence is
    # only assertable where BOTH models treat the component the same way, so a component is
    # exempt if EITHER model declares it non-StateVariable.
    roles_a = state_variable_roles(reactive_xml)
    roles_b = state_variable_roles(nonreactive_xml)
    ao, bo = a.get("outlet", {}), b.get("outlet", {})
    all_shared = sorted(set(ao) & set(bo))
    shared = [c for c in all_shared
              if roles_a.get(c, "StateVariable") == "StateVariable"
              and roles_b.get(c, "StateVariable") == "StateVariable"]
    exempt = [c for c in all_shared if c not in shared]
    role_mismatch = [c for c in all_shared
                     if roles_a.get(c) and roles_b.get(c) and roles_a[c] != roles_b[c]]
    if not shared:
        return {"ok": False, "rung": "5b", "stage": "compare",
                "reason": "the two models share no outlet components to compare"}
    diffs, worst, worst_c = [], 0.0, None
    for c in shared:
        va, vb = ao.get(c), bo.get(c)
        if va is None or vb is None:
            continue
        rel = abs(va - vb) / max(abs(vb), 1e-9)
        if rel > worst:
            worst, worst_c = rel, c
        if rel > tol:
            diffs.append({"component": c, "reactive": va, "nonreactive": vb, "rel": rel})
    return {"ok": not diffs, "rung": "5b", "stage": "complete",
            "reason": ("reactive-with-rates-zeroed matches non-reactive"
                       if not diffs else f"{len(diffs)} component(s) differ"),
            "n_compared": len(shared), "n_exempt_by_design": len(exempt),
            "role_mismatch": role_mismatch[:8],
            "exempt": exempt[:8],
            "worst_component": worst_c, "worst_rel": worst,
            "differences": diffs[:8]}


if __name__ == "__main__":                                   # pragma: no cover
    print(__doc__)
