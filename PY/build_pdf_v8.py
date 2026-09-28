"""
Build SUMO24_MCP_Tools_Reference.pdf — v10
──────────────────────────────────────────
Extracts every types.Tool() definition from server.py, groups them
heuristically by category, and renders a clean reference PDF with:
  - title page + overview
  - per-group tables (name + description)
  - table of contents with tool counts
v10: Adds Group EE (Build Pack & Baseline Apply) — 3 new tools that
replace the broken Group DD zip-as-.sumo approach. Group DD tools are
marked DEPRECATED in their descriptions.
"""
from __future__ import annotations
import re
from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether,
)

# ── parse server.py ────────────────────────────────────────────────────────
SRC = Path(__file__).parent / "server.py"
text = SRC.read_text(encoding="utf-8")

# extract (name, description) pairs
TOOL_RE = re.compile(
    r'types\.Tool\(\s*'
    r'name\s*=\s*"([^"]+)"\s*,\s*'
    r'description\s*=\s*(?:\(\s*)?(.+?)(?:\s*\))?\s*,\s*'
    r'inputSchema',
    re.DOTALL,
)

def _clean(s: str) -> str:
    # strip outer paren+quotes, collapse string concatenation
    parts = re.findall(r'"((?:\\.|[^"\\])*)"', s)
    if parts:
        s = "".join(parts)
    # collapse whitespace
    s = re.sub(r"\s+", " ", s).strip()
    # escape XML/paraparser meta-chars (& must come first)
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return s


def _safe(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

tools: list[tuple[str, str]] = [(n, _clean(d)) for n, d in TOOL_RE.findall(text)]
print(f"Parsed {len(tools)} tools from server.py")

# ── classify into groups ──────────────────────────────────────────────────
def classify(name: str) -> str:
    n = name.lower()
    # Group EE — Build Pack & Baseline Apply (must match before Group DD)
    if n in ("build_sumo_pack", "apply_schematic_to_baseline", "validate_sumoslang"):
        return "Group EE — Build Pack & Baseline Apply"
    # Group DD — Schematic-to-SUMO File Compiler (DEPRECATED tools)
    if n in ("compile_schematic_to_sumo", "build_sumo_from_html",
             "preview_sumo_manifest", "attach_companion_dll",
             "verify_sumo_file_against_schematic", "read_sumo_manifest"):
        return "Group DD — Schematic-to-SUMO Compiler (Deprecated)"
    # Group CC — Troubleshooting (must match before validation_)
    if n in ("diagnose_sumo_file", "scan_sumo_directory", "check_dll_companion",
             "repair_sumo_file", "diagnose_sumo_crash", "validate_sumo_environment",
             "list_sumo_diagnostics"):
        return "Group CC — SUMO Troubleshooting"
    # Group BB — HTML Schematic
    if n in ("import_schematic_from_html", "build_model_from_schematic",
             "compare_schematic_to_model", "generate_sumoslang_from_schematic",
             "list_schematic_unit_types"):
        return "Group BB — HTML Schematic ↔ SUMO"
    # Group AA — WWTP Template
    if n in ("generate_wwtp_template_xlsx", "read_wwtp_template",
             "validate_wwtp_template", "build_model_from_template"):
        return "Group AA — WWTP Excel Template"
    # Group Z — Academic exports
    if n.startswith("export_") and ("academic" in n or "latex" in n or
                                     "publication" in n or "calibration" in n or
                                     "statistical" in n or "scenario_comparison" in n or
                                     "multi_file" in n or "sensitivity_tornado" in n or
                                     "box_plot" in n or "mass_balance_diagram" in n):
        return "Group Z — Academic Export"
    if n.startswith("export_") or n.startswith("generate_report") or n == "plot_time_series_chart":
        return "Group Z — Academic Export"
    # Group Y — optimisation / diagnostics / economics
    if n.startswith("optimize_") or n.startswith("diagnose_") or n.startswith("recommend_") \
       or n in ("estimate_annual_opex", "estimate_ghg_emissions",
                "compute_removal_efficiencies_from_dataset",
                "compare_dataset_vs_simulation", "apply_dataset_to_model",
                "scan_parameter_sensitivity", "check_compliance"):
        return "Group Y — Optimisation / Diagnostics / Economics"
    # Group X — validation
    if n.startswith("validate_") or n.startswith("ensure_") or n == "check_dataset_against_law48":
        return "Group X — Validation"
    # Group H — datasets
    if "dataset" in n or n in ("get_law48_limits_from_excel", "list_dataset_measurement_points",
                                "map_dataset_to_sumo_variables", "read_dataset_excel",
                                "create_dynamic_input_table", "import_influent_profile",
                                "apply_influent_from_dataset", "apply_point_to_unit",
                                "export_simulation_to_dataset", "get_measurement_point_data",
                                "get_parameter_across_points", "search_variables",
                                "list_state_variables", "get_state_variable"):
        return "Group H — Datasets"
    # Group G — parameters
    if n.startswith("set_") or n.startswith("get_parameter") or n.startswith("list_parameters") \
       or n in ("reset_parameter_to_default", "validate_variable_name",
                "set_multiple_parameters", "set_parameter", "set_parameter_persistent",
                "assume_parameters_from_research", "apply_temperature_correction"):
        return "Group G — Parameters"
    # Group F — scenarios
    if "scenario" in n:
        return "Group F — Scenarios"
    # Group E — model lifecycle
    if n in ("load_model", "save_model", "compile_model", "extract_dll", "get_compile_status",
             "create_model", "get_model_info", "initialize_state", "save_state", "load_state",
             "list_saved_states"):
        return "Group E — Model Lifecycle"
    # Group D — topology editing
    if n in ("add_unit_process", "remove_unit_process", "connect_unit_processes",
             "add_recycle_stream", "modify_flow_connection", "list_unit_processes",
             "list_flow_streams", "list_available_unit_process_types",
             "list_available_kinetic_models", "get_unit_process_info", "add_controller"):
        return "Group D — Topology Editing"
    # Group C — diagnostics / convergence
    if n in ("get_effluent_statistics", "get_mass_balance", "get_sludge_production",
             "get_energy_estimate", "list_completed_jobs", "get_job_status",
             "ensure_dtt_bridge"):
        return "Group C — Reports & Diagnostics"
    # Group B — simulations
    if n in ("run_steady_state", "run_dynamic_simulation", "run_scenario_comparison",
             "set_dynamic_simulation_parameters"):
        return "Group B — Simulation Runs"
    # Group A — core
    return "Group A — Core / Influent / Misc"

groups: dict[str, list[tuple[str, str]]] = {}
for name, desc in tools:
    g = classify(name)
    groups.setdefault(g, []).append((name, desc))

# canonical ordering
ORDER = [
    "Group A — Core / Influent / Misc",
    "Group B — Simulation Runs",
    "Group C — Reports & Diagnostics",
    "Group D — Topology Editing",
    "Group E — Model Lifecycle",
    "Group F — Scenarios",
    "Group G — Parameters",
    "Group H — Datasets",
    "Group X — Validation",
    "Group Y — Optimisation / Diagnostics / Economics",
    "Group Z — Academic Export",
    "Group AA — WWTP Excel Template",
    "Group BB — HTML Schematic ↔ SUMO",
    "Group CC — SUMO Troubleshooting",
    "Group DD — Schematic-to-SUMO Compiler (Deprecated)",
    "Group EE — Build Pack & Baseline Apply",
]

# ── render PDF ─────────────────────────────────────────────────────────────
OUT = Path(r"F:\UNI\SUMO\MCP\SUMO24_MCP_Tools_Reference.pdf")
doc = SimpleDocTemplate(
    str(OUT), pagesize=A4,
    leftMargin=18*mm, rightMargin=18*mm, topMargin=18*mm, bottomMargin=18*mm,
    title="SUMO24 MCP Tools Reference",
    author="SUMO24 MCP Server",
)
styles = getSampleStyleSheet()
title = ParagraphStyle("Title", parent=styles["Title"], fontSize=22, leading=26)
h1    = ParagraphStyle("H1",    parent=styles["Heading1"], fontSize=14, spaceBefore=12, spaceAfter=6, textColor=colors.HexColor("#1a2128"))
h2    = ParagraphStyle("H2",    parent=styles["Heading2"], fontSize=11, spaceBefore=6,  spaceAfter=2)
body  = ParagraphStyle("Body",  parent=styles["BodyText"], fontSize=9, leading=12)
mono  = ParagraphStyle("Mono",  parent=styles["Code"], fontSize=8, leading=10, textColor=colors.HexColor("#2e5e7e"))
small = ParagraphStyle("Small", parent=styles["BodyText"], fontSize=8, leading=10)

story = []

# ── Title page ───────────────────────────────────────────────────────────
story += [
    Paragraph("SUMO24 MCP Tools Reference", title),
    Spacer(1, 4*mm),
    Paragraph(f"<b>{len(tools)} tools</b> exposed by the SUMO24 MCP server", h2),
    Paragraph("Generated from <font face='Courier'>server.py</font> · revision v10", small),
    Spacer(1, 8*mm),
    Paragraph(
        "This reference catalogues every tool the SUMO24 MCP server exposes to Claude. "
        "Tools are grouped functionally — core simulation control at the top, then "
        "diagnostics, scenarios, parameters, datasets, validation, optimisation, academic "
        "exports, the WWTP Excel template pipeline (Group AA), the HTML schematic builder "
        "pipeline (Group BB), the SUMO file troubleshooting package (Group CC), the "
        "deprecated schematic-to-SUMO zip compiler (Group DD — produces files SUMO24 "
        "cannot load; retained for read_sumo_manifest compatibility), and the replacement "
        "build-pack pipeline (Group EE) that produces a <font face='Courier'>.sumo-pack/</font> "
        "directory with a compilable SumoSlang definition and parameter script the user "
        "applies inside SUMO24 GUI to get a real, loadable project. "
        "All tools are callable through the MCP protocol; each accepts a JSON object "
        "matching its inputSchema and returns a JSON-encoded TextContent.",
        body,
    ),
    Spacer(1, 6*mm),
]

# overview table
overview = [["Group", "Tool count"]]
total_in_groups = 0
for g in ORDER:
    n = len(groups.get(g, []))
    overview.append([g, str(n)])
    total_in_groups += n
overview.append(["TOTAL", str(total_in_groups)])
ovr = Table(overview, colWidths=[110*mm, 30*mm])
ovr.setStyle(TableStyle([
    ("FONT",       (0,0), (-1,0), "Helvetica-Bold", 10),
    ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#1a2128")),
    ("TEXTCOLOR",  (0,0), (-1,0), colors.white),
    ("BACKGROUND", (0,-1),(-1,-1),colors.HexColor("#c8a04a")),
    ("FONT",       (0,-1),(-1,-1),"Helvetica-Bold", 10),
    ("FONT",       (0,1), (-1,-2), "Helvetica", 9),
    ("ROWBACKGROUNDS", (0,1),(-1,-2), [colors.white, colors.HexColor("#f4f3ee")]),
    ("GRID", (0,0),(-1,-1), 0.3, colors.HexColor("#d8d4c8")),
    ("ALIGN",(1,0),(1,-1), "CENTER"),
    ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
    ("LEFTPADDING",(0,0),(-1,-1), 6),
    ("RIGHTPADDING",(0,0),(-1,-1), 6),
    ("TOPPADDING",(0,0),(-1,-1), 4),
    ("BOTTOMPADDING",(0,0),(-1,-1), 4),
]))
story += [ovr, PageBreak()]

# ── per-group sections ──────────────────────────────────────────────────
for g in ORDER:
    items = groups.get(g) or []
    if not items:
        continue
    story.append(Paragraph(g, h1))
    story.append(Paragraph(f"<i>{len(items)} tools</i>", small))
    story.append(Spacer(1, 2*mm))

    rows = [["Tool", "Description"]]
    for nm, desc in items:
        rows.append([
            Paragraph(f"<font face='Courier'>{_safe(nm)}</font>", small),
            Paragraph(desc, small),
        ])
    tbl = Table(rows, colWidths=[55*mm, 115*mm])
    tbl.setStyle(TableStyle([
        ("FONT",       (0,0), (-1,0), "Helvetica-Bold", 9),
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#2e5e7e")),
        ("TEXTCOLOR",  (0,0), (-1,0), colors.white),
        ("ROWBACKGROUNDS", (0,1),(-1,-1), [colors.white, colors.HexColor("#f4f3ee")]),
        ("GRID", (0,0),(-1,-1), 0.25, colors.HexColor("#d8d4c8")),
        ("VALIGN",(0,0),(-1,-1),"TOP"),
        ("LEFTPADDING",(0,0),(-1,-1), 5),
        ("RIGHTPADDING",(0,0),(-1,-1), 5),
        ("TOPPADDING",(0,0),(-1,-1), 3),
        ("BOTTOMPADDING",(0,0),(-1,-1), 3),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 5*mm))

# ── trailer ──────────────────────────────────────────────────────────────
story += [
    PageBreak(),
    Paragraph("Pipeline Overview", h1),
    Paragraph(
        "<b>WWTP Excel Template pipeline (Group AA):</b> generate_wwtp_template_xlsx → "
        "fill the workbook → validate_wwtp_template → build_model_from_template. "
        "Builds a SUMO24 model from scratch, with sizing, operational parameters, "
        "and influent characteristics applied via the DTT bridge.",
        body),
    Spacer(1, 3*mm),
    Paragraph(
        "<b>HTML Schematic pipeline (Group BB):</b> open wwtp_schematic_template.html in a browser, "
        "build the plant using Configuration mode + Connection mode (loops supported for RAS/IR), "
        "click \"Save HTML (for MCP)\", then import_schematic_from_html → "
        "compare_schematic_to_model → build_model_from_schematic. "
        "Use generate_sumoslang_from_schematic for stretch-goal topology generation.",
        body),
    Spacer(1, 3*mm),
    Paragraph(
        "<b>Troubleshooting (Group CC):</b> when a .sumo file won't open or simulate, "
        "start with validate_sumo_environment, then diagnose_sumo_file or scan_sumo_directory. "
        "check_dll_companion confirms the sumoproject.dll is present; repair_sumo_file fixes the "
        "most common issues (empty file, missing DLL, missing state.xml, wrong extension). "
        "diagnose_sumo_crash parses recent SUMO logs for known error signatures. "
        "list_sumo_diagnostics returns the full catalogue of remediations.",
        body),
]

doc.build(story)
print(f"OK Wrote {OUT}  ({OUT.stat().st_size:,} bytes)")
