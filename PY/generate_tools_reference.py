"""
generate_tools_reference.py
Regenerate SUMO24_MCP_Tools_Reference.pdf from the tool list the server ACTUALLY serves.
Run from the PY/ directory:  python generate_tools_reference.py

[2026-09-07] SOURCE CHANGED, and the reason matters. This script used to read `server.py` as
TEXT, hunting for `types.Tool(` literals. That works only while every tool is a literal, and
Group HH registers its 24 dynamically from `hh_tools.TOOL_DEFS` (one source of truth instead of
24 duplicated literals). The static reader was blind to them - and, it turned out, to Group GG's
21 GUI tools as well. **The PDF was already 21 tools out of date before Group HH existed, and
nothing reported it.**

So the primary source is now `server.list_tools()` - what the running server exposes - with the
static parse kept only as a fallback for a tool the live import cannot reach. The same change
`check_registration_runtime.py` made for the regression harness, for the same reason.

A COVERAGE GATE now runs before the PDF is built: a registered tool missing from GROUPS aborts
the build instead of quietly producing a reference that omits it. A tools reference that is
silently incomplete is worse than no reference, because it is trusted.
"""
import re, os, sys, asyncio, textwrap
from xml.sax.saxutils import escape as xml_escape
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, HRFlowable,
)

# ── 1. Extract tool names + descriptions from server.py ──────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (_HERE, os.path.dirname(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

LIVE_TOOLS: dict[str, str] = {}
LIVE_OK = False
try:
    import server as _server
    for _t in asyncio.run(_server.list_tools()):
        LIVE_TOOLS[_t.name] = re.sub(r"\s+", " ", (_t.description or "")).strip()
    LIVE_OK = True
    print(f"Live server exposes {len(LIVE_TOOLS)} tools")
except Exception as _e:                                     # pragma: no cover
    print(f"WARNING - could not import the live server ({type(_e).__name__}: {_e});"
          f" falling back to the static parse, which CANNOT see dynamically registered tools")

SERVER_PY = os.path.join(os.path.dirname(__file__), "server.py")
with open(SERVER_PY, encoding="utf-8", errors="replace") as f:
    src = f.read()

TOOL_DESCS: dict[str, str] = {}

def _extract_desc(chunk: str) -> str | None:
    """Pull description= from a Tool(...) chunk; handles both forms:
       description="..."            -- simple string
       description=("a" "b" ...)   -- parenthesised concatenation
    """
    # Form 1: description=( ... )  -- find matching close-paren after description=(
    m = re.search(r'description=\(', chunk)
    if m:
        start = m.end()
        depth = 1
        i = start
        while i < len(chunk) and depth:
            if chunk[i] == '(':
                depth += 1
            elif chunk[i] == ')':
                depth -= 1
            i += 1
        raw = chunk[start: i - 1]
        parts = re.findall(r'"(.*?)"', raw, re.DOTALL)
        if parts:
            return re.sub(r'\s+', ' ', ''.join(parts)).strip()
    # Form 2: description="..."
    m = re.search(r'description="(.*?)"', chunk, re.DOTALL)
    if m:
        return re.sub(r'\s+', ' ', m.group(1)).strip()
    return None

# Locate each types.Tool( block by offset; grab up to 2500 chars for parsing.
for m_start in re.finditer(r'types\.Tool\(', src):
    chunk = src[m_start.start(): m_start.start() + 2500]
    m_name = re.search(r'name="([a-z][a-z0-9_]+)"', chunk)
    if not m_name:
        continue
    name = m_name.group(1)
    desc = _extract_desc(chunk)
    if desc:
        TOOL_DESCS[name] = desc

# The live list wins wherever it has an entry: it is what the server actually serves.
TOOL_DESCS.update({k: v for k, v in LIVE_TOOLS.items() if v})
if LIVE_OK:
    for _n in LIVE_TOOLS:
        TOOL_DESCS.setdefault(_n, "(no description)")

# ── 2. Group mapping ──────────────────────────────────────────────────────────
GROUPS = [
    ("B", "Simulation Runs", [
        "run_steady_state", "run_dynamic_simulation",
    ]),
    ("C", "Reports & Diagnostics", [
        "get_job_status", "get_effluent_statistics", "get_sludge_production",
        "get_energy_estimate", "list_completed_jobs", "get_mass_balance",
    ]),
    ("D", "Topology Editing", [
        "list_unit_processes", "get_unit_process_info",
        "list_available_unit_process_types", "add_unit_process",
        "remove_unit_process", "rename_unit_process", "change_unit_type",
        "list_available_kinetic_models",
        "connect_unit_processes", "add_recycle_stream",
        "modify_flow_connection", "remove_flow_connection", "set_stream_flow_rate",
        "list_flow_streams",
        "add_controller", "list_controllers", "modify_controller", "remove_controller",
        "ensure_dtt_bridge",
    ]),
    ("E", "Model Lifecycle", [
        "get_model_info", "save_state", "load_state", "list_saved_states",
        "get_compile_status", "create_model", "load_model", "save_model",
        "compile_model", "extract_dll", "initialize_state",
    ]),
    ("F", "Scenarios", [
        "run_scenario_comparison", "list_scenarios", "create_scenario",
        "update_scenario", "delete_scenario", "clone_scenario",
        "get_scenario_diff", "import_scenario",
        # export_scenario lives in Group Z (Academic Export)
    ]),
    ("G", "Parameters", [
        "set_parameter", "get_parameter", "list_parameters",
        "set_multiple_parameters", "reset_parameter_to_default",
        "set_kinetic_model", "set_influent_characteristics", "set_fractionation",
        "set_parameter_persistent",
        "set_asm1_kinetics", "set_asm2d_kinetics", "set_asm3_kinetics",
        "apply_temperature_correction", "set_plant_wide_parameters",
        "set_influent_parameters", "set_primary_clarifier_parameters",
        "set_aeration_tank_parameters", "set_anoxic_zone_parameters",
        "set_anaerobic_zone_parameters", "set_secondary_clarifier_parameters",
        "set_mbr_parameters", "set_ras_was_parameters", "set_digester_parameters",
        "set_chemical_dosing_parameters", "set_dynamic_simulation_parameters",
        "assume_parameters_from_research",
    ]),
    ("H", "Datasets", [
        "create_dynamic_input_table",
        "list_state_variables", "get_state_variable", "get_state_variables",
        "extract_sumo_data", "search_variables",
        "import_influent_profile",
        "read_dataset_excel", "list_dataset_measurement_points",
        "get_measurement_point_data", "get_parameter_across_points",
        "get_law48_limits_from_excel", "map_dataset_to_sumo_variables",
        "validate_dataset", "check_dataset_against_law48",
        "apply_influent_from_dataset", "apply_point_to_unit",
    ]),
    ("X", "Validation", [
        "validate_variable_name", "validate_model", "validate_model_structure",
        "validate_influent_configuration",
        "validate_mass_balance_pre_run", "validate_mass_balance_post_run",
        "validate_mlss_health", "validate_srt_fm_feasibility",
        "validate_do_levels", "validate_oxygen_demand_vs_supply",
        "validate_hydraulic_balance", "validate_asm_kinetics",
        "validate_simulation_convergence", "validate_simulation_plausibility",
        "validate_full_model", "validate_post_simulation",
        # validate_sumo_environment lives in Group CC (SUMO Troubleshooting)
    ]),
    ("Y", "Optimisation / Diagnostics / Economics", [
        "check_compliance",
        "apply_dataset_to_model", "compare_dataset_vs_simulation",
        "compute_removal_efficiencies_from_dataset",
        "scan_parameter_sensitivity",
        "optimize_was_for_target_srt", "optimize_kla_for_target_do",
        "diagnose_nitrification_failure", "diagnose_bulking_risk",
        "diagnose_phosphorus_removal", "recommend_setpoint_adjustments",
        "estimate_annual_opex", "estimate_ghg_emissions",
    ]),
    ("Z", "Academic Export", [
        "export_results_csv", "export_scenario", "generate_report",
        "export_simulation_to_dataset", "export_comparison_report",
        "plot_time_series_chart", "export_publication_time_series",
        "export_calibration_parity_plot", "export_scenario_comparison_bar_chart",
        "export_sensitivity_tornado_diagram", "export_box_plot_distributions",
        "export_academic_results_table_docx", "export_academic_bundle",
        "export_latex_results_table", "export_statistical_summary_xlsx",
        "export_academic_report_docx", "export_multi_file_batch_comparison",
        "export_mass_balance_diagram",
    ]),
    ("AA", "WWTP Excel Template", [
        "generate_wwtp_template_xlsx", "read_wwtp_template",
        "validate_wwtp_template", "build_model_from_template",
        "apply_template_auto_fixes",
    ]),
    ("BB", "HTML Schematic → SUMO", [
        "import_schematic_from_html", "build_model_from_schematic",
        "compare_schematic_to_model", "generate_sumoslang_from_schematic",
        "list_schematic_unit_types", "update_schematic_in_html",
    ]),
    ("CC", "SUMO Troubleshooting", [
        "diagnose_sumo_file", "scan_sumo_directory", "check_dll_companion",
        "repair_sumo_file", "diagnose_sumo_crash",
        "validate_sumo_environment", "list_sumo_diagnostics",
    ]),
    ("DD", "Schematic-to-SUMO Compiler", [
        "compile_schematic_to_sumo", "build_sumo_from_html",
        "preview_sumo_manifest", "attach_companion_dll",
        "verify_sumo_file_against_schematic", "read_sumo_manifest",
        "build_sumo_pack", "apply_schematic_to_baseline",
        "build_native_sumo", "topology_match_report",
        "validate_sumoslang", "verify_dll_matches_schematic",
    ]),
    ("EE", "Modelling Pipeline", [
        "next_step_for_project",
        "pipeline_init", "pipeline_status", "pipeline_advance",
        "pipeline_revert", "pipeline_describe",
        "stage1_open_schematic", "stage1_validate_schematic",
        "stage2_open_data", "stage2_validate_parameters",
        "stage3_run_engineering_checks",
        "stage4_define_static_inputs", "stage4_validate_static_inputs",
        "stage5_generate_dynamic_inputs", "stage5_validate_dynamic_inputs",
        "stage6_add_controller", "stage6_validate_controllers",
        "stage7_build", "stage8_verify",
    ]),
    ("FF", "DTT Edit & Transactions", [
        "begin_edit_transaction", "commit_edit_transaction",
        "rollback_edit_transaction", "apply_dtt_command_batch",
        "diff_inmemory_vs_disk",
    ]),
    ("GG", "SUMO GUI Automation", [
        "launch_sumo_gui", "gui_focus_sumo", "gui_get_window_rect", "gui_screenshot",
        "gui_switch_tab", "gui_click_at", "gui_drag_from_to", "gui_send_keys",
        "gui_type_text", "gui_close_dialog",
        "gui_list_palette_items", "gui_capture_palette_template",
        "gui_calibrate_palette_item", "gui_find_icon_by_template",
        "gui_add_unit_to_canvas", "gui_drop_unit_at", "gui_drop_unit_by_template",
        "gui_connect_units", "gui_open_unit_properties", "gui_set_param_in_dialog",
        "gui_save_sumo",
    ]),
    ("HH", "SumoSlang Unit Authoring", [
        # spec lifecycle
        "hh_describe_process_unit", "hh_compose_unit_spec", "hh_read_unit_spec",
        "hh_edit_unit_spec", "hh_review_unit_spec", "hh_accept_unit_spec",
        # the seven-rung acceptance ladder
        "hh_lint_unit_spec", "hh_check_dimensions", "hh_check_continuity",
        "hh_diff_model_base", "hh_compile_smt", "hh_compile_slcompiler",
        "hh_run_tracer_test",
        # emission
        "hh_emit_unit_workbook", "hh_emit_icon", "hh_emit_test_plant",
        "hh_fork_model_base", "hh_add_unit_to_calibrated_plant",
        # install and support
        "hh_install_process_unit", "hh_check_environment", "hh_run_ladder",
        # cleanup and rollback
        "hh_clean_build", "hh_snapshot_build", "hh_revert_build",
    ]),
]

# Verify coverage
all_grouped = {t for _, _, tools in GROUPS for t in tools}
all_known   = set(TOOL_DESCS.keys())
unclassified = all_known - all_grouped
duplicate    = [t for _, _, tools in GROUPS for t in tools
                if list(t for _, _, g in GROUPS for t2 in g if t2 == t).count(t) > 1]
print(f"Extracted {len(TOOL_DESCS)} tool descriptions "
      f"({'live server' if LIVE_OK else 'STATIC PARSE ONLY'})")

# THE COVERAGE GATE. A registered tool absent from GROUPS aborts the build.
# This is not tidiness: the previous version printed a warning and built the PDF anyway, and
# that is exactly how 21 GUI tools stayed missing from the reference without anyone noticing.
if LIVE_OK:
    missing = sorted(set(LIVE_TOOLS) - all_grouped)
    stale = sorted(all_grouped - set(LIVE_TOOLS))
    if missing:
        raise SystemExit(
            f"REFUSING to build the PDF: {len(missing)} registered tool(s) are not in any "
            f"group and would be silently omitted: {missing}\n"
            f"Add them to GROUPS. A reference that is quietly incomplete is worse than none.")
    if stale:
        raise SystemExit(
            f"REFUSING to build the PDF: {len(stale)} tool(s) are grouped but NOT registered "
            f"by the server: {stale}\nThe reference would document tools nobody can call.")
    print(f"Coverage gate: PASS - all {len(LIVE_TOOLS)} registered tools are grouped")
elif unclassified:
    print(f"WARNING — unclassified tools ({len(unclassified)}): {sorted(unclassified)}")

# Total tool count
TOTAL = sum(len(tools) for _, _, tools in GROUPS)
print(f"Total grouped: {TOTAL}")

# ── 3. Styles ─────────────────────────────────────────────────────────────────
styles = getSampleStyleSheet()

HEAD1 = ParagraphStyle(
    "Head1", parent=styles["Heading1"],
    fontSize=18, spaceAfter=6, spaceBefore=0,
    textColor=colors.HexColor("#1a3a5c"),
)
HEAD2 = ParagraphStyle(
    "Head2", parent=styles["Heading2"],
    fontSize=13, spaceAfter=4, spaceBefore=10,
    textColor=colors.HexColor("#1a3a5c"),
)
BODY = ParagraphStyle(
    "Body", parent=styles["Normal"],
    fontSize=9, leading=13,
)
SMALL = ParagraphStyle(
    "Small", parent=styles["Normal"],
    fontSize=8, leading=11, textColor=colors.HexColor("#444444"),
)
TOOL_NAME = ParagraphStyle(
    "ToolName", parent=styles["Normal"],
    fontSize=9, leading=12, fontName="Courier-Bold",
)
TOOL_DESC = ParagraphStyle(
    "ToolDesc", parent=styles["Normal"],
    fontSize=9, leading=12,
)
COVER_TITLE = ParagraphStyle(
    "CoverTitle", parent=styles["Title"],
    fontSize=24, textColor=colors.HexColor("#1a3a5c"),
    spaceAfter=8,
)
COVER_SUB = ParagraphStyle(
    "CoverSub", parent=styles["Normal"],
    fontSize=12, textColor=colors.HexColor("#444444"), spaceAfter=4,
)

ACCENT = colors.HexColor("#1a3a5c")
LIGHT   = colors.HexColor("#e8eef4")
WHITE   = colors.white

# ── 4. Build story ────────────────────────────────────────────────────────────
story = []

# ── Cover page ────────────────────────────────────────────────────────────────
story.append(Spacer(1, 2*cm))
story.append(Paragraph("SUMO24 MCP Tools Reference", COVER_TITLE))
story.append(Paragraph(f"{TOTAL} tools exposed by the SUMO24 MCP server", COVER_SUB))
story.append(Paragraph(
    "Generated from the live server tool list — revision v11", COVER_SUB))
story.append(Spacer(1, 0.5*cm))
story.append(HRFlowable(width="100%", thickness=2, color=ACCENT))
story.append(Spacer(1, 0.4*cm))
story.append(Paragraph(
    "This reference catalogues every tool the SUMO24 MCP server exposes to Claude. "
    "Tools are grouped functionally — core simulation control at the top, then "
    "diagnostics, scenarios, parameters, datasets, validation, optimisation, academic "
    "exports, the WWTP Excel template pipeline (Group AA), the HTML schematic builder "
    "pipeline (Group BB), the SUMO file troubleshooting package (Group CC), the "
    "schematic-to-SUMO compiler pipeline (Group DD), the guided modelling pipeline "
    "(Group EE), the DTT edit-transaction batch layer (Group FF), the SUMO GUI "
    "automation surface (Group GG), and the SumoSlang unit-authoring toolchain "
    "(Group HH). "
    "All tools are callable through the MCP protocol; each accepts a JSON object "
    "matching its inputSchema and returns a JSON-encoded TextContent.",
    BODY,
))
story.append(Spacer(1, 0.6*cm))

# Summary table
tbl_data = [
    [Paragraph("<b>Group</b>", BODY), Paragraph("<b>Name</b>", BODY),
     Paragraph("<b>Tool count</b>", BODY)],
]
for grp, name, tools in GROUPS:
    tbl_data.append([
        Paragraph(f"Group {grp}", BODY),
        Paragraph(name, BODY),
        Paragraph(str(len(tools)), BODY),
    ])
tbl_data.append([
    Paragraph("<b>TOTAL</b>", BODY), Paragraph("", BODY),
    Paragraph(f"<b>{TOTAL}</b>", BODY),
])

tbl = Table(tbl_data, colWidths=[2.5*cm, 10*cm, 2.5*cm])
tbl.setStyle(TableStyle([
    ("BACKGROUND",  (0, 0), (-1, 0),  ACCENT),
    ("TEXTCOLOR",   (0, 0), (-1, 0),  WHITE),
    ("BACKGROUND",  (0, -1),(-1, -1), LIGHT),
    ("ROWBACKGROUNDS", (0, 1), (-1, -2), [WHITE, LIGHT]),
    ("GRID",        (0, 0), (-1, -1), 0.5, colors.HexColor("#b0c0d0")),
    ("VALIGN",      (0, 0), (-1, -1), "TOP"),
    ("TOPPADDING",  (0, 0), (-1, -1), 4),
    ("BOTTOMPADDING",(0,0), (-1, -1), 4),
    ("LEFTPADDING", (0, 0), (-1, -1), 6),
]))
story.append(tbl)
story.append(PageBreak())

# ── One page per group ────────────────────────────────────────────────────────
def tool_table(tools):
    rows = [[
        Paragraph("<b>Tool</b>", BODY),
        Paragraph("<b>Description</b>", BODY),
    ]]
    for t in tools:
        desc = xml_escape(TOOL_DESCS.get(t, "(description not found in server.py)"))
        rows.append([
            Paragraph(t, TOOL_NAME),
            Paragraph(desc, TOOL_DESC),
        ])
    tbl = Table(rows, colWidths=[5.5*cm, 11.5*cm])
    tbl.setStyle(TableStyle([
        ("BACKGROUND",  (0, 0), (-1, 0), ACCENT),
        ("TEXTCOLOR",   (0, 0), (-1, 0), WHITE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT]),
        ("GRID",        (0, 0), (-1, -1), 0.4, colors.HexColor("#c0cdd8")),
        ("VALIGN",      (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING",  (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING",(0,0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
    ]))
    return tbl

for grp, name, tools in GROUPS:
    story.append(Paragraph(f"Group {grp} — {name}", HEAD2))
    story.append(Paragraph(f"{len(tools)} tool{'s' if len(tools)!=1 else ''}", SMALL))
    story.append(Spacer(1, 0.2*cm))
    story.append(tool_table(tools))
    story.append(Spacer(1, 0.5*cm))

story.append(PageBreak())

# ── Pipeline overview (last page) ─────────────────────────────────────────────
story.append(Paragraph("Pipeline Overview", HEAD2))
story.append(Spacer(1, 0.2*cm))

pipelines = [
    ("WWTP Excel Template (Group AA)",
     "generate_wwtp_template_xlsx → fill the workbook → validate_wwtp_template "
     "→ build_model_from_template. Builds a SUMO24 model from scratch, with sizing, "
     "operational parameters, and influent characteristics applied via the DTT bridge. "
     "apply_template_auto_fixes corrects common structural issues before building."),
    ("HTML Schematic (Group BB)",
     "Open wwtp_schematic_template.html in a browser, build the plant using Configuration "
     "mode + Connection mode (loops supported for RAS/IR), click “Save HTML (for MCP)”, "
     "then import_schematic_from_html → compare_schematic_to_model → "
     "build_model_from_schematic. update_schematic_in_html writes a revised schematic back "
     "into the HTML. Use generate_sumoslang_from_schematic for stretch-goal topology generation."),
    ("Troubleshooting (Group CC)",
     "When a .sumo file won’t open or simulate, start with validate_sumo_environment, "
     "then diagnose_sumo_file or scan_sumo_directory. check_dll_companion confirms the "
     "sumoproject.dll is present; repair_sumo_file fixes the most common issues. "
     "diagnose_sumo_crash parses recent SUMO logs for known error signatures. "
     "list_sumo_diagnostics returns the full catalogue of remediations."),
    ("Schematic-to-SUMO Compiler (Group DD)",
     "compile_schematic_to_sumo or (preferred one-call) build_sumo_from_html → "
     "attach_companion_dll → verify_sumo_file_against_schematic → read_sumo_manifest. "
     "build_native_sumo handles full native-format builds; build_sumo_pack wraps the "
     "project into a distributable archive. topology_match_report, validate_sumoslang, "
     "and verify_dll_matches_schematic are available for post-build verification."),
    ("Guided Modelling Pipeline (Group EE)",
     "next_step_for_project picks the right entry point. Structured path: "
     "pipeline_init → stage1_open_schematic / stage1_validate_schematic → "
     "stage2_open_data / stage2_validate_parameters → stage3_run_engineering_checks → "
     "stage4_define_static_inputs / stage4_validate_static_inputs → "
     "stage5_generate_dynamic_inputs / stage5_validate_dynamic_inputs → "
     "stage6_add_controller / stage6_validate_controllers → stage7_build → stage8_verify. "
     "pipeline_status, pipeline_advance, pipeline_revert, and pipeline_describe manage "
     "progress through the pipeline."),
    ("SumoSlang Unit Authoring (Group HH)",
     "Author a NEW process unit from a natural-language description, in seven verified steps. "
     "Describe: hh_describe_process_unit (prose) or hh_compose_unit_spec (explicit fields) \u2192 "
     "hh_edit_unit_spec fills values \u2192 hh_review_unit_spec / hh_accept_unit_spec record "
     "explicit human acceptance. Verify, in order: hh_lint_unit_spec (rung 1) \u2192 "
     "hh_check_dimensions (1.5) \u2192 hh_check_continuity (2) \u2192 hh_diff_model_base (2.5, "
     "Type B only) \u2192 hh_compile_smt (3) \u2192 hh_compile_slcompiler (4) \u2192 "
     "hh_run_tracer_test (5). hh_run_ladder sequences rungs 1\u20132 and stops at the first "
     "failure. Emit: hh_emit_unit_workbook + hh_emit_icon + hh_emit_test_plant (SMT compiles a "
     "PLANT, never a bare unit). hh_fork_model_base handles Type B. hh_install_process_unit is "
     "the ONLY tool that writes into the SUMO installation, it needs an explicit opt-in, and it "
     "writes only into the user overlay. "
     "Two rules run through all of it: STRUCTURE MAY BE INFERRED, MAGNITUDES MAY NOT \u2014 no "
     "tool here writes a number nobody supplied; and NO TOOL TRUSTS AN EXIT CODE \u2014 SMT24 "
     "returns 0 on a reader error, slcompiler returns 0 while logging [ERROR], and the DTT "
     "scheduler returns a job id even when the model failed to load."),
    ("SUMO GUI Automation (Group GG)",
     "For the parts of SUMO that have no headless equivalent. launch_sumo_gui \u2192 "
     "gui_focus_sumo \u2192 gui_screenshot to see the window state. Palette work: "
     "gui_list_palette_items, gui_capture_palette_template and gui_calibrate_palette_item build "
     "a template library; gui_find_icon_by_template and gui_drop_unit_by_template then place "
     "units reliably. gui_connect_units draws streams; gui_open_unit_properties + "
     "gui_set_param_in_dialog edit a unit; gui_save_sumo persists. Prefer the headless tools "
     "wherever they exist \u2014 GUI automation is positional and brittle by nature."),
    ("DTT Edit & Transactions (Group FF)",
     "begin_edit_transaction (snapshots state.xml) → apply_dtt_command_batch "
     "(dispatches vetted executeCommand strings in bulk) → commit_edit_transaction "
     "(persists changes) or rollback_edit_transaction (restores snapshot). "
     "diff_inmemory_vs_disk reports what needs save_model / reload to bring the live "
     "in-memory model into sync with a .sumo on disk."),
]

for title, text in pipelines:
    story.append(Paragraph(f"<b>{title}</b>", BODY))
    story.append(Paragraph(text, BODY))
    story.append(Spacer(1, 0.3*cm))

# ── 5. Build PDF ──────────────────────────────────────────────────────────────
OUT = os.path.join(os.path.dirname(__file__), "..", "SUMO24_MCP_Tools_Reference.pdf")
doc = SimpleDocTemplate(
    OUT, pagesize=A4,
    leftMargin=2*cm, rightMargin=2*cm,
    topMargin=2*cm, bottomMargin=2*cm,
    title="SUMO24 MCP Tools Reference",
    author="SUMO24 MCP",
    subject=f"{TOTAL} tools",
)
doc.build(story)
print(f"Written: {os.path.abspath(OUT)}")
