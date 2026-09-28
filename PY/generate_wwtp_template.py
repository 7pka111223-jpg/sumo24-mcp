"""
Generates WWTP_Model_Input_Template.xlsx in F:\\UNI\\SUMO\\MCP.

Run this once from a Windows PowerShell / CMD:

    cd F:\\UNI\\SUMO\\MCP\\PY
    python generate_wwtp_template.py

The resulting workbook can be filled in and consumed by the SUMO24 MCP
tool `build_model_from_template` to construct a SUMO24 model from scratch.
"""
from pathlib import Path
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.comments import Comment

OUT_PATH = Path(__file__).resolve().parent.parent / "WWTP_Model_Input_Template.xlsx"

# ── Style palette ──────────────────────────────────────────────────────────
HEADER_FILL = PatternFill("solid", start_color="1F3864")
NOTE_FILL   = PatternFill("solid", start_color="FFF2CC")
INPUT_FILL  = PatternFill("solid", start_color="DEEBF7")
OPT_FILL    = PatternFill("solid", start_color="F2F2F2")

HEADER_FONT = Font(name="Calibri", bold=True, size=11, color="FFFFFF")
TITLE_FONT  = Font(name="Calibri", bold=True, size=16, color="1F3864")
SECTION_FONT = Font(name="Calibri", bold=True, size=12, color="1F3864")
BODY_FONT   = Font(name="Calibri", size=10)
UNIT_FONT   = Font(name="Calibri", italic=True, size=9, color="595959")
NOTE_FONT   = Font(name="Calibri", italic=True, size=10, color="555555")

THIN  = Side(border_style="thin",  color="BFBFBF")
THICK = Side(border_style="medium", color="1F3864")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
HEAD_BORDER = Border(left=THICK, right=THICK, top=THICK, bottom=THICK)

CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
LEFT   = Alignment(horizontal="left",   vertical="center", wrap_text=True)


def hdr(cell):
    cell.font = HEADER_FONT; cell.fill = HEADER_FILL
    cell.border = HEAD_BORDER; cell.alignment = CENTER


def title(ws, txt, ncols):
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ncols)
    c = ws.cell(row=1, column=1, value=txt)
    c.font = TITLE_FONT
    c.alignment = LEFT
    ws.row_dimensions[1].height = 24


def widths(ws, ws_widths):
    for i, w in enumerate(ws_widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w


def input_block(ws, top_row, last_row, n_cols):
    for r in range(top_row, last_row + 1):
        for c in range(1, n_cols + 1):
            cl = ws.cell(row=r, column=c)
            cl.font = BODY_FONT; cl.fill = INPUT_FILL; cl.border = BOX
            cl.alignment = LEFT


# ═══════════════════════════════════════════════════════════════════════════
# Build the workbook
# ═══════════════════════════════════════════════════════════════════════════
wb = Workbook()

# ── README ────────────────────────────────────────────────────────────────
ws = wb.active
ws.title = "README"
title(ws, "WWTP Model Input Template — SUMO24 MCP", 2)
widths(ws, [32, 100])
readme_rows = [
    ("Purpose",
     "Fill this workbook with the available data for your wastewater treatment "
     "plant. The SUMO24 MCP server can read it with `read_wwtp_template`, "
     "validate it with `validate_wwtp_template`, and build a SUMO24 model from "
     "scratch with `build_model_from_template`."),
    ("Workflow",
     "1) Plant_Info  2) Influent_Dataset & Influent_Fractionation  "
     "3) Effluent_Dataset & Effluent_Targets  4) Treatment_Processes  "
     "5) Connections  6) Process_Sizing  7) Bio/Phys/Chem_Operational  "
     "8) Save and call `build_model_from_template`."),
    ("Cell colour key",
     "Navy header rows are not editable. Pale-blue cells are user inputs. "
     "Gray cells contain unit hints. Yellow cells are notes."),
    ("Required vs optional",
     "Plant_Info, Treatment_Processes and Connections are required. Other "
     "sheets are optional but improve calibration quality."),
    ("Time-series sheets",
     "Influent_Dataset and Effluent_Dataset accept daily or sub-daily "
     "timestamps (yyyy-mm-dd or yyyy-mm-dd HH:MM). Missing values may be left blank."),
    ("Variable_Map",
     "Reference sheet listing the SUMO state variables that map to each column."),
    ("Tip — units",
     "Concentrations in mg/L; flows in m3/d; T in degC; volumes in m3; areas in m2; "
     "alkalinity in mmol/L."),
    ("Tip — order matters",
     "Treatment_Processes.order_index controls the topological order in which "
     "units are added — keep Influent first, Effluent last."),
    ("Egyptian context",
     "Effluent_Targets is preloaded with Law 48/1982 default limits."),
]
ws.cell(row=2, column=1, value="Section").font = SECTION_FONT
ws.cell(row=2, column=2, value="Description").font = SECTION_FONT
for i, (k, v) in enumerate(readme_rows, start=3):
    ws.cell(row=i, column=1, value=k).font = Font(bold=True, size=11)
    ws.cell(row=i, column=2, value=v).font = BODY_FONT
    for c in (1, 2):
        ws.cell(row=i, column=c).alignment = Alignment(
            horizontal="left", vertical="top", wrap_text=True)
    ws.row_dimensions[i].height = 48


# ── Plant_Info ────────────────────────────────────────────────────────────
ws = wb.create_sheet("Plant_Info")
title(ws, "1. Plant Information", 4)
widths(ws, [38, 32, 14, 60])
for c, h in enumerate(["Field", "Value", "Unit", "Description / hint"], start=1):
    hdr(ws.cell(row=3, column=c, value=h))
pi_rows = [
    ("project_name",          "MyPlant_2026",     "-",          "Identifier used for the .sumo file and folder name."),
    ("project_path",          "F:/UNI/SUMO/MCP/projects", "-",  "Absolute folder where the project will be created."),
    ("plant_location",        "",                 "-",          "City, country, or coordinates."),
    ("design_flow_avg",       "",                 "m3/d",       "Average dry-weather design flow."),
    ("design_flow_peak",      "",                 "m3/d",       "Peak hourly design flow."),
    ("design_flow_min",       "",                 "m3/d",       "Minimum night-time flow."),
    ("design_population",     "",                 "PE",         "Design population equivalent."),
    ("kinetic_model",         "ASM2d",            "-",          "ASM1 / ASM2d / ASM3 / ASM3+BioP / Mantis2."),
    ("temperature_design",    "20",               "degC",       "Reference design temperature."),
    ("temperature_min",       "",                 "degC",       "Coldest expected temperature."),
    ("temperature_max",       "",                 "degC",       "Hottest expected temperature."),
    ("elevation",             "",                 "m a.s.l.",   "Plant elevation."),
    ("discharge_target",      "law48_drain",      "-",          "law48_nile / law48_drain / custom."),
    ("project_currency",      "EGP",              "-",          "Reporting currency for OPEX/CAPEX."),
    ("created_by",            "",                 "-",          "Engineer or modeller name."),
    ("created_date",          "",                 "yyyy-mm-dd", "Date of template completion."),
]
for i, (field, val, unit, desc) in enumerate(pi_rows, start=4):
    ws.cell(row=i, column=1, value=field).font = Font(bold=True, size=10)
    ws.cell(row=i, column=2, value=val).fill = INPUT_FILL
    ws.cell(row=i, column=3, value=unit).font = UNIT_FONT
    ws.cell(row=i, column=4, value=desc).font = NOTE_FONT
    for c in range(1, 5):
        ws.cell(row=i, column=c).border = BOX
        ws.cell(row=i, column=c).alignment = LEFT
dv = DataValidation(type="list",
    formula1='"ASM1,ASM2d,ASM3,ASM3+BioP,Mantis2,MBR_ASM2d,ADM1"', allow_blank=True)
dv.add("B11"); ws.add_data_validation(dv)
dv = DataValidation(type="list",
    formula1='"law48_nile,law48_drain,custom"', allow_blank=True)
dv.add("B16"); ws.add_data_validation(dv)
ws.freeze_panes = "A4"


# ── Influent_Dataset / Effluent_Dataset ───────────────────────────────────
inf_cols = [
    ("Date",        "yyyy-mm-dd",      "Daily timestamp; sub-daily allowed."),
    ("Q",           "m3/d",            "Influent flow rate."),
    ("COD",         "mg/L",            "Total chemical oxygen demand."),
    ("sCOD",        "mg/L",            "Soluble (filtered) COD."),
    ("BOD5",        "mg/L",            "5-day biochemical oxygen demand."),
    ("TSS",         "mg/L",            "Total suspended solids."),
    ("VSS",         "mg/L",            "Volatile suspended solids."),
    ("TKN",         "mg/L",            "Total Kjeldahl nitrogen."),
    ("NH4-N",       "mg/L",            "Ammonia nitrogen."),
    ("NO3-N",       "mg/L",            "Nitrate nitrogen."),
    ("TP",          "mg/L",            "Total phosphorus."),
    ("PO4-P",       "mg/L",            "Ortho-phosphate phosphorus."),
    ("Alkalinity",  "mmol/L",          "Bicarbonate alkalinity."),
    ("pH",          "-",               "pH (use median if range)."),
    ("Temperature", "degC",            "Influent temperature."),
]
for sheet_name, sheet_title in [
    ("Influent_Dataset", "2. Influent Dataset (time series)"),
    ("Effluent_Dataset", "4. Effluent Dataset (time series)"),
]:
    ws = wb.create_sheet(sheet_name)
    title(ws, sheet_title, len(inf_cols))
    widths(ws, [16] + [13] * (len(inf_cols) - 1))
    for c, (h, u, desc) in enumerate(inf_cols, start=1):
        hcell = ws.cell(row=3, column=c, value=h); hdr(hcell)
        ucell = ws.cell(row=4, column=c, value=u)
        ucell.font = UNIT_FONT; ucell.alignment = CENTER
        ucell.fill = OPT_FILL; ucell.border = BOX
        hcell.comment = Comment(desc, "SUMO24 MCP")
    input_block(ws, 5, 34, len(inf_cols))
    ws.freeze_panes = "B5"


# ── Influent_Fractionation ────────────────────────────────────────────────
ws = wb.create_sheet("Influent_Fractionation")
title(ws, "3. Influent COD/N/P Fractionation", 4)
widths(ws, [22, 16, 14, 70])
for c, h in enumerate(["Fraction", "Value", "Unit", "Description"], start=1):
    hdr(ws.cell(row=3, column=c, value=h))
frac_rows = [
    ("fSI",   0.07, "g COD/g COD", "Soluble inert (SI) fraction of total COD."),
    ("fSS",   0.20, "g COD/g COD", "Readily biodegradable (SS) fraction."),
    ("fXS",   0.50, "g COD/g COD", "Slowly biodegradable (XS) fraction."),
    ("fXI",   0.15, "g COD/g COD", "Particulate inert (XI) fraction."),
    ("fXBH",  0.08, "g COD/g COD", "Heterotrophic biomass fraction."),
    ("fXBA",  0.00, "g COD/g COD", "Autotrophic biomass fraction."),
    ("fSNH4", 0.65, "g N/g TKN",   "Ammonia (NH4) fraction of TKN."),
    ("fSND",  0.10, "g N/g TKN",   "Soluble biodegradable organic N."),
    ("fXND",  0.18, "g N/g TKN",   "Particulate biodegradable organic N."),
    ("fSI_N", 0.02, "g N/g COD",   "Soluble inert N content."),
    ("fXI_N", 0.05, "g N/g COD",   "Particulate inert N content."),
    ("fSPO4", 0.50, "g P/g TP",    "Ortho-phosphate fraction of TP."),
    ("fXPP",  0.00, "g P/g TP",    "Poly-phosphate fraction (PAOs)."),
    ("fSI_P", 0.005, "g P/g COD",  "Soluble inert P content."),
    ("fXI_P", 0.01,  "g P/g COD",  "Particulate inert P content."),
]
for i, (k, v, u, d) in enumerate(frac_rows, start=4):
    ws.cell(row=i, column=1, value=k).font = Font(bold=True, size=10)
    ws.cell(row=i, column=2, value=v).fill = INPUT_FILL
    ws.cell(row=i, column=3, value=u).font = UNIT_FONT
    ws.cell(row=i, column=4, value=d).font = NOTE_FONT
    for c in range(1, 5):
        ws.cell(row=i, column=c).border = BOX
        ws.cell(row=i, column=c).alignment = LEFT
i = 4 + len(frac_rows) + 1
ws.cell(row=i, column=1, value="Sum (fSI+fSS+fXS+fXI+fXBH+fXBA)").font = Font(bold=True, italic=True)
ws.cell(row=i, column=2, value="=SUM(B4:B9)").fill = NOTE_FILL
ws.cell(row=i, column=3, value="should ≈ 1.0").font = UNIT_FONT
ws.cell(row=i, column=4, value="If far from 1.0, revisit fractionation.").font = NOTE_FONT
for c in range(1, 5):
    ws.cell(row=i, column=c).border = BOX
ws.freeze_panes = "A4"


# ── Effluent_Targets ──────────────────────────────────────────────────────
ws = wb.create_sheet("Effluent_Targets")
title(ws, "5. Effluent Discharge Targets / Permit Limits", 5)
widths(ws, [16, 14, 14, 14, 60])
for c, h in enumerate(["Parameter", "Limit", "Unit", "Stat", "Source / notes"], start=1):
    hdr(ws.cell(row=3, column=c, value=h))
tgt_rows = [
    ("BOD5",   60,  "mg/L", "max", "Egyptian Law 48/1982 — agricultural drains."),
    ("COD",    80,  "mg/L", "max", "Egyptian Law 48/1982 — agricultural drains."),
    ("TSS",    50,  "mg/L", "max", "Egyptian Law 48/1982 — agricultural drains."),
    ("NH4-N",   5,  "mg/L", "max", "Egyptian Law 48/1982 — agricultural drains."),
    ("TN",     50,  "mg/L", "max", "Egyptian Law 48/1982 — agricultural drains."),
    ("TP",      3,  "mg/L", "max", "Egyptian Law 48/1982 — agricultural drains."),
    ("Oil",    10,  "mg/L", "max", "Egyptian Law 48/1982 — agricultural drains."),
    ("FC",   5000, "MPN/100mL", "max", "Faecal coliforms — agricultural reuse."),
    ("pH_min", 6.0, "-",    "min", "Egyptian Law 48/1982."),
    ("pH_max", 9.0, "-",    "max", "Egyptian Law 48/1982."),
]
for i, (p, l, u, s, src) in enumerate(tgt_rows, start=4):
    ws.cell(row=i, column=1, value=p).font = Font(bold=True, size=10)
    ws.cell(row=i, column=2, value=l).fill = INPUT_FILL
    ws.cell(row=i, column=3, value=u).font = UNIT_FONT
    ws.cell(row=i, column=4, value=s).font = UNIT_FONT
    ws.cell(row=i, column=5, value=src).font = NOTE_FONT
    for c in range(1, 6):
        ws.cell(row=i, column=c).border = BOX
        ws.cell(row=i, column=c).alignment = LEFT
ws.freeze_panes = "A4"


# ── Treatment_Processes ───────────────────────────────────────────────────
ws = wb.create_sheet("Treatment_Processes")
title(ws, "6. Treatment Processes (physical / biological / chemical)", 7)
widths(ws, [10, 22, 22, 14, 14, 16, 50])
for c, h in enumerate(
    ["order_index","instance_name","process_type","category","stage","kinetic_model","notes"],
    start=1):
    hdr(ws.cell(row=3, column=c, value=h))
sample_procs = [
    (1,  "Influent",          "Influent",            "physical",   "headworks",   "",       "Raw wastewater inflow."),
    (2,  "Screen1",           "Screen",              "physical",   "headworks",   "",       "Bar screen, 6 mm spacing."),
    (3,  "GritChamber1",      "GritChamber",         "physical",   "headworks",   "",       "Aerated grit chamber."),
    (4,  "PrimaryClarifier1", "PrimaryClarifier",    "physical",   "primary",     "",       "Circular primary clarifier."),
    (5,  "AnaerobicTank1",    "AnaerobicReactor",    "biological", "biological",  "ASM2d",  "Selector / anaerobic zone for EBPR."),
    (6,  "AnoxicTank1",       "AnoxicReactor",       "biological", "biological",  "ASM2d",  "Pre-denitrification."),
    (7,  "AerationTank1",     "AerationTank",        "biological", "biological",  "ASM2d",  "Plug-flow aeration tank."),
    (8,  "SecondaryClarifier1","SecondaryClarifier", "physical",   "secondary",   "Takacs", "Circular Takacs clarifier."),
    (9,  "TertiaryFilter1",   "SandFilter",          "physical",   "tertiary",    "",       "Optional tertiary filtration."),
    (10, "DisinfectionUnit1", "UVDisinfection",      "physical",   "tertiary",    "",       "UV disinfection."),
    (11, "ChemDoser_FeCl3",   "ChemicalDoser",       "chemical",   "secondary",   "",       "FeCl3 dose for P precipitation."),
    (12, "Thickener1",        "GravityThickener",    "physical",   "sludge",      "",       "WAS thickening."),
    (13, "Digester1",         "AnaerobicDigester",   "biological", "sludge",      "ADM1",   "Mesophilic anaerobic digester."),
    (14, "Dewatering1",       "Centrifuge",          "physical",   "sludge",      "",       "Sludge dewatering."),
    (15, "Effluent",          "Effluent",            "physical",   "effluent",    "",       "Treated effluent discharge."),
]
for i, row in enumerate(sample_procs, start=4):
    for c, v in enumerate(row, start=1):
        cell = ws.cell(row=i, column=c, value=v)
        cell.font = BODY_FONT; cell.fill = INPUT_FILL; cell.border = BOX; cell.alignment = LEFT
input_block(ws, 4 + len(sample_procs), 4 + len(sample_procs) + 9, 7)
dv = DataValidation(type="list", formula1='"physical,biological,chemical"', allow_blank=True)
dv.add("D4:D200"); ws.add_data_validation(dv)
dv = DataValidation(type="list",
    formula1='"headworks,primary,biological,secondary,tertiary,disinfection,sludge,effluent"',
    allow_blank=True)
dv.add("E4:E200"); ws.add_data_validation(dv)
dv = DataValidation(type="list",
    formula1='"ASM1,ASM2d,ASM3,ASM3+BioP,Mantis2,MBR_ASM2d,Takacs,ADM1,Siegrist,CSTR_Simple"',
    allow_blank=True)
dv.add("F4:F200"); ws.add_data_validation(dv)
ws.freeze_panes = "A4"


# ── Connections ───────────────────────────────────────────────────────────
ws = wb.create_sheet("Connections")
title(ws, "7. Stream Connections (process network)", 6)
widths(ws, [22, 22, 22, 14, 14, 50])
for c, h in enumerate(
    ["from_unit","to_unit","stream_name","stream_type","recycle_type","notes"],
    start=1):
    hdr(ws.cell(row=3, column=c, value=h))
sample_conns = [
    ("Influent",            "Screen1",              "S_inf_screen",  "liquid",  "",                "Raw → screening."),
    ("Screen1",             "GritChamber1",         "S_screen_grit", "liquid",  "",                "Screened → grit."),
    ("GritChamber1",        "PrimaryClarifier1",    "S_grit_prim",   "liquid",  "",                "Grit-removed → primary."),
    ("PrimaryClarifier1",   "AnaerobicTank1",       "S_prim_ana",    "liquid",  "",                "Primary effluent → anaerobic."),
    ("AnaerobicTank1",      "AnoxicTank1",          "S_ana_anox",    "liquid",  "",                "Anaerobic → anoxic."),
    ("AnoxicTank1",         "AerationTank1",        "S_anox_aer",    "liquid",  "",                "Anoxic → aeration."),
    ("AerationTank1",       "SecondaryClarifier1",  "S_aer_sec",     "liquid",  "",                "Aeration → secondary clarifier."),
    ("SecondaryClarifier1", "TertiaryFilter1",      "S_sec_tert",    "liquid",  "",                "Clarified → tertiary."),
    ("TertiaryFilter1",     "DisinfectionUnit1",    "S_tert_disinf", "liquid",  "",                "Tertiary → UV."),
    ("DisinfectionUnit1",   "Effluent",             "S_disinf_eff",  "liquid",  "",                "UV → effluent."),
    ("AerationTank1",       "AnoxicTank1",          "S_IR",          "recycle", "InternalRecycle", "Internal nitrate recycle."),
    ("SecondaryClarifier1", "AnoxicTank1",          "S_RAS",         "recycle", "RAS",             "Return activated sludge."),
    ("SecondaryClarifier1", "Thickener1",           "S_WAS",         "recycle", "WAS",             "Waste activated sludge."),
    ("PrimaryClarifier1",   "Digester1",            "S_PSL",         "sludge",  "",                "Primary sludge → digester."),
    ("Thickener1",          "Digester1",            "S_TWAS",        "sludge",  "",                "Thickened WAS → digester."),
    ("Digester1",           "Dewatering1",          "S_DigOut",      "sludge",  "",                "Digested sludge → centrifuge."),
    ("Dewatering1",         "AerationTank1",        "S_Reject",      "recycle", "RejectWater",     "Centrate back to aeration."),
    ("ChemDoser_FeCl3",     "AerationTank1",        "S_FeCl3",       "liquid",  "",                "FeCl3 dose into aeration tank."),
]
for i, row in enumerate(sample_conns, start=4):
    for c, v in enumerate(row, start=1):
        cell = ws.cell(row=i, column=c, value=v)
        cell.font = BODY_FONT; cell.fill = INPUT_FILL; cell.border = BOX; cell.alignment = LEFT
input_block(ws, 4 + len(sample_conns), 4 + len(sample_conns) + 9, 6)
dv = DataValidation(type="list", formula1='"liquid,sludge,gas,recycle"', allow_blank=True)
dv.add("D4:D200"); ws.add_data_validation(dv)
dv = DataValidation(type="list",
    formula1='"RAS,WAS,InternalRecycle,RejectWater,Sidestream"', allow_blank=True)
dv.add("E4:E200"); ws.add_data_validation(dv)
ws.freeze_panes = "A4"


# ── Process_Sizing ────────────────────────────────────────────────────────
ws = wb.create_sheet("Process_Sizing")
title(ws, "8. Process Sizing (per unit)", 10)
widths(ws, [22] + [13] * 9)
for c, h in enumerate(
    ["instance_name","n_units","volume_m3","depth_m","surface_area_m2",
     "diameter_m","length_m","width_m","HRT_h","notes"], start=1):
    hdr(ws.cell(row=3, column=c, value=h))
size_rows = [
    ("Screen1",              1, "",   "", "",  "",  "",  "", "",  "Mechanical bar screen."),
    ("GritChamber1",         1, 50,   2,  "",  "",  "",  "", 1.0, "Aerated grit chamber."),
    ("PrimaryClarifier1",    1, 800,  3.5,230, 17, "",  "", 2.0, "Circular primary clarifier."),
    ("AnaerobicTank1",       1, 600,  4.0,"", "",  25,  6, 0.6, "Anaerobic selector."),
    ("AnoxicTank1",          1, 1200, 4.0,"", "",  30, 10, 1.2, "Pre-denitrification."),
    ("AerationTank1",        2, 4000, 4.5,"", "",  40, 22, 6.0, "Two parallel aeration tanks."),
    ("SecondaryClarifier1",  2, 1500, 4.0,380, 22, "",  "", 3.5, "Two circular Takacs clarifiers."),
    ("TertiaryFilter1",      2, "",   "", 60,  "", "",  "", "",  "Sand / dual-media filters."),
    ("DisinfectionUnit1",    1, 50,   1.5,30,  "", 10,  3, 0.2, "UV channel."),
    ("Thickener1",           1, 200,  3.0,70,  "", "",  "", 6.0, "Gravity thickener."),
    ("Digester1",            1, 3000, 8.0,"",  "", "",  "", 480, "Mesophilic digester (HRT in hours)."),
    ("Dewatering1",          1, "",   "", "",  "", "",  "", "",  "Centrifuge — flow basis only."),
]
for i, row in enumerate(size_rows, start=4):
    for c, v in enumerate(row, start=1):
        cell = ws.cell(row=i, column=c, value=v)
        cell.font = BODY_FONT; cell.fill = INPUT_FILL; cell.border = BOX; cell.alignment = LEFT
input_block(ws, 4 + len(size_rows), 4 + len(size_rows) + 9, 10)
ws.freeze_panes = "A4"


# ── Bio_Operational ───────────────────────────────────────────────────────
ws = wb.create_sheet("Bio_Operational")
title(ws, "9. Biological-Process Operational Parameters", 6)
widths(ws, [22, 22, 14, 14, 14, 50])
for c, h in enumerate(
    ["instance_name","parameter","value","unit","applies_to","notes"], start=1):
    hdr(ws.cell(row=3, column=c, value=h))
bio_rows = [
    ("AerationTank1", "DO_setpoint",      2.0,  "mg/L",              "aeration",  "DO setpoint."),
    ("AerationTank1", "kLa",              "",   "1/h",               "aeration",  "Override automatic kLa."),
    ("AerationTank1", "MLSS_target",      3500, "mg/L",              "aeration",  "Target MLSS."),
    ("AerationTank1", "SRT_target",       12,   "d",                 "aeration",  "Target solids retention time."),
    ("AerationTank1", "F_M_target",       0.20, "kgBOD/(kgMLVSS·d)", "aeration",  "F:M ratio."),
    ("AerationTank1", "Temperature_op",   22,   "degC",              "aeration",  "Operating temperature."),
    ("AnoxicTank1",   "Mixing_power",     6,    "W/m3",              "anoxic",    "Mechanical mixing power."),
    ("AnoxicTank1",   "DO_max",           0.2,  "mg/L",              "anoxic",    "Maximum DO."),
    ("AnaerobicTank1","Mixing_power",     6,    "W/m3",              "anaerobic", "Mechanical mixing power."),
    ("AnaerobicTank1","DO_max",           0.05, "mg/L",              "anaerobic", "Strict anaerobic ceiling."),
    ("SecondaryClarifier1","RAS_ratio",   0.75, "-",                 "RAS",       "Q_RAS / Q_inf."),
    ("SecondaryClarifier1","WAS_ratio",   0.02, "-",                 "WAS",       "Q_WAS / Q_inf."),
    ("AnoxicTank1",   "Internal_recycle_ratio", 3.0, "-",            "IR",        "Q_IR / Q_inf."),
    ("Digester1",     "Temperature_op",   35,   "degC",              "anaerobic", "Mesophilic T."),
    ("Digester1",     "HRT",              20,   "d",                 "anaerobic", "Hydraulic retention time."),
    ("Digester1",     "VS_loading",       2.0,  "kgVS/(m3·d)",       "anaerobic", "Volatile-solids loading."),
]
for i, row in enumerate(bio_rows, start=4):
    for c, v in enumerate(row, start=1):
        cell = ws.cell(row=i, column=c, value=v)
        cell.font = BODY_FONT; cell.fill = INPUT_FILL; cell.border = BOX; cell.alignment = LEFT
input_block(ws, 4 + len(bio_rows), 4 + len(bio_rows) + 14, 6)
ws.freeze_panes = "A4"


# ── Phys_Operational ──────────────────────────────────────────────────────
ws = wb.create_sheet("Phys_Operational")
title(ws, "10. Physical-Process Operational Parameters", 6)
widths(ws, [22, 22, 14, 14, 14, 50])
for c, h in enumerate(
    ["instance_name","parameter","value","unit","applies_to","notes"], start=1):
    hdr(ws.cell(row=3, column=c, value=h))
phy_rows = [
    ("Screen1",            "bar_spacing",       6,   "mm",         "screen",       "Bar spacing."),
    ("Screen1",            "approach_velocity", 0.6, "m/s",        "screen",       "At peak."),
    ("GritChamber1",       "HRT",               3,   "min",        "grit",         "At peak flow."),
    ("GritChamber1",       "air_supply",        0.3, "m3/(m·min)", "grit",         "Air per metre length."),
    ("PrimaryClarifier1",  "SOR_avg",           32,  "m3/(m2·d)",  "clarifier",    "SOR @ average flow."),
    ("PrimaryClarifier1",  "SOR_peak",          80,  "m3/(m2·d)",  "clarifier",    "SOR @ peak."),
    ("PrimaryClarifier1",  "weir_loading",      125, "m3/(m·d)",   "clarifier",    "Weir overflow."),
    ("SecondaryClarifier1","SLR_avg",           4.0, "kg/(m2·h)",  "clarifier",    "Solids loading."),
    ("SecondaryClarifier1","SOR_avg",           24,  "m3/(m2·d)",  "clarifier",    "SOR."),
    ("TertiaryFilter1",    "filtration_rate",   8,   "m/h",        "filter",       "Loading rate."),
    ("TertiaryFilter1",    "backwash_rate",     30,  "m/h",        "filter",       "Backwash."),
    ("DisinfectionUnit1",  "UV_dose",           40,  "mJ/cm2",     "disinfection", "At peak."),
    ("Thickener1",         "SLR",               90,  "kg/(m2·d)",  "thickener",    "Solids loading rate."),
    ("Dewatering1",        "polymer_dose",      8,   "g/kgDS",     "dewatering",   "Cationic polymer."),
    ("Dewatering1",        "cake_solids_target",22,  "%TS",        "dewatering",   "Target cake DS."),
]
for i, row in enumerate(phy_rows, start=4):
    for c, v in enumerate(row, start=1):
        cell = ws.cell(row=i, column=c, value=v)
        cell.font = BODY_FONT; cell.fill = INPUT_FILL; cell.border = BOX; cell.alignment = LEFT
input_block(ws, 4 + len(phy_rows), 4 + len(phy_rows) + 14, 6)
ws.freeze_panes = "A4"


# ── Chem_Operational ──────────────────────────────────────────────────────
ws = wb.create_sheet("Chem_Operational")
title(ws, "11. Chemical Dosing", 6)
widths(ws, [22, 18, 12, 14, 14, 50])
for c, h in enumerate(
    ["instance_name","chemical","dose","unit","target_unit","purpose"], start=1):
    hdr(ws.cell(row=3, column=c, value=h))
chem_rows = [
    ("ChemDoser_FeCl3", "FeCl3",     50, "mg/L", "AerationTank1", "Phosphorus precipitation."),
    ("",                "Alum",      "",  "mg/L", "",              "Coagulation / P removal."),
    ("",                "PACl",      "",  "mg/L", "",              "Coagulation / P removal."),
    ("",                "Polymer",   "",  "mg/L", "",              "Flocculation aid."),
    ("",                "NaOH",      "",  "mg/L", "",              "Alkalinity / pH adjustment."),
    ("",                "Ca(OH)2",   "",  "mg/L", "",              "pH / disinfection."),
    ("",                "Methanol",  "",  "mg/L", "",              "External carbon for denitrification."),
    ("",                "Acetate",   "",  "mg/L", "",              "External carbon."),
    ("",                "Cl2",       "",  "mg/L", "",              "Disinfection."),
    ("",                "NaOCl",     "",  "mg/L", "",              "Disinfection."),
]
for i, row in enumerate(chem_rows, start=4):
    for c, v in enumerate(row, start=1):
        cell = ws.cell(row=i, column=c, value=v)
        cell.font = BODY_FONT; cell.fill = INPUT_FILL; cell.border = BOX; cell.alignment = LEFT
input_block(ws, 4 + len(chem_rows), 4 + len(chem_rows) + 4, 6)
dv = DataValidation(type="list",
    formula1='"FeCl3,FeSO4,Alum,PACl,Polymer,NaOH,Ca(OH)2,Methanol,Acetate,Glycerol,Cl2,NaOCl,KMnO4,O3"',
    allow_blank=True)
dv.add("B4:B100"); ws.add_data_validation(dv)
ws.freeze_panes = "A4"


# ── Variable_Map ──────────────────────────────────────────────────────────
ws = wb.create_sheet("Variable_Map")
title(ws, "12. Variable Map (column → SUMO state variable)", 4)
widths(ws, [16, 28, 18, 60])
for c, h in enumerate(["Column header", "SUMO state var", "Unit", "Notes"], start=1):
    hdr(ws.cell(row=3, column=c, value=h))
vmap = [
    ("Q",           "Q",    "m3/d",  "Volumetric flow rate."),
    ("COD",         "TCOD", "mg/L",  "Total COD."),
    ("sCOD",        "SCOD", "mg/L",  "Soluble COD (SI + SS)."),
    ("BOD5",        "BOD5", "mg/L",  "BOD5; computed from COD if absent."),
    ("TSS",         "TSS",  "mg/L",  "Total suspended solids."),
    ("VSS",         "VSS",  "mg/L",  "Volatile suspended solids."),
    ("TKN",         "TKN",  "mg/L",  "Total Kjeldahl nitrogen."),
    ("NH4-N",       "SNH",  "mg/L",  "Ammonia."),
    ("NO3-N",       "SNO",  "mg/L",  "Nitrate + nitrite."),
    ("TP",          "TP",   "mg/L",  "Total phosphorus."),
    ("PO4-P",       "SPO",  "mg/L",  "Ortho-phosphate."),
    ("Alkalinity",  "SALK", "mmol/L","Bicarbonate alkalinity."),
    ("pH",          "PH",   "-",     "pH (informational only)."),
    ("Temperature", "T",    "degC",  "Bulk-liquid temperature."),
]
for i, row in enumerate(vmap, start=4):
    for c, v in enumerate(row, start=1):
        cell = ws.cell(row=i, column=c, value=v)
        cell.font = BODY_FONT
        cell.fill = OPT_FILL
        cell.border = BOX
        cell.alignment = LEFT
ws.freeze_panes = "A4"


# ── Save ──────────────────────────────────────────────────────────────────
wb.save(OUT_PATH)
print(f"OK Saved: {OUT_PATH}")
print(f"   Size:   {OUT_PATH.stat().st_size} bytes")
print(f"   Sheets: {wb.sheetnames}")
