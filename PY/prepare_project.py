"""
prepare_project.py
==================
Run this ONCE before starting the MCP server.

It extracts the compiled model DLL and initial system state XML
from your .sumo project file using the Dynamita `tool` module.

Usage:
  python prepare_project.py --project "C:/Projects/Qaha_WWTP.sumo" --scenario "Baseline"
"""

import argparse
import sys
from pathlib import Path

# Add MCP root to sys.path so `import dynamita` finds MCP/dynamita/
_MCP_DIR = Path(__file__).parent.parent
if str(_MCP_DIR) not in sys.path:
    sys.path.insert(0, str(_MCP_DIR))

def main():
    parser = argparse.ArgumentParser(description="Prepare SUMO24 project for MCP server")
    parser.add_argument("--project",  required=True, help="Path to your .sumo project file")
    parser.add_argument("--out_dir",  default=".",    help="Output directory for dll and state.xml")
    parser.add_argument("--scenario", default="",     help="Scenario name for parameter extraction (optional)")
    args = parser.parse_args()

    project = Path(args.project)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not project.exists():
        print(f"ERROR: Project file not found: {project}")
        sys.exit(1)

    try:
        from dynamita import tool as dt
    except ImportError:
        print("ERROR: Cannot import dynamita.tool. Make sure the DTT addon is installed")
        print("and the `dynamita` folder is in your Python path or next to this script.")
        sys.exit(1)

    # ── Step 1: Extract compiled model DLL ───────────────────────────────────
    print(f"Extracting DLL from {project} ...")
    dll_path = out_dir / "sumoproject.dll"
    ok = dt.extract_dll_from_project(str(project), str(out_dir))
    if not ok:
        print("ERROR: DLL extraction failed. Make sure you compiled the project in the GUI first.")
        sys.exit(1)
    print(f"  → DLL saved to {dll_path}")

    # ── Step 2: Extract initial parameters as a SumoCore script ─────────────
    print(f"Extracting parameters as SumoCore script ...")
    tsv_dir    = str(out_dir / "tsv_inputs")
    script_out = str(out_dir / "state.scs")
    Path(tsv_dir).mkdir(exist_ok=True)

    ok = dt.extract_parameters_from_project(
        project  = str(project),
        tsvdir   = tsv_dir,
        script_to= script_out,
        scenario = args.scenario,
    )
    if not ok:
        print("WARNING: Parameter extraction returned False. Check the project and scenario name.")
    else:
        print(f"  → SumoCore init script saved to {script_out}")

    print("\nDone. Update server.py CONFIG with:")
    print(f'  "model_dll":  "{dll_path}"')
    print(f'  "state_xml":  "state.xml"  (or state.scs if using script-based init)')
    print()
    print("To generate state.xml: open the Core Window in SUMO GUI,")
    print('  run your model to steady-state, then type: maptoic; save "state.xml"')

if __name__ == "__main__":
    main()
