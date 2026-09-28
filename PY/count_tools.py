"""Count tools defined in server.py and print group breakdown."""
import re
from pathlib import Path

src = Path("server.py").read_text(encoding="utf-8")
names = re.findall(r'types\.Tool\(\s*name="([^"]+)"', src)
print(f"Total tools: {len(names)}")
print(f"Last 20: {names[-20:]}")
# Group BB tools we expect to see:
bb = ["import_schematic_from_html", "build_model_from_schematic",
      "compare_schematic_to_model", "generate_sumoslang_from_schematic",
      "list_schematic_unit_types"]
cc = ["diagnose_sumo_file", "scan_sumo_directory", "check_dll_companion",
      "repair_sumo_file", "diagnose_sumo_crash", "validate_sumo_environment",
      "list_sumo_diagnostics"]
for n in bb + cc:
    print(f"  {n!r} present: {n in names}")
