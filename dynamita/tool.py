import os
import zipfile
import xml.etree.ElementTree as ET
import datetime
import threading
import random

msec = 1
sec  = 1000 * msec
minute  = 60 * sec
hour = 60 * minute
day  = 24 * hour
week = 7 * day

class OPCEntry:
    def __init__(self):
        self.io = "I"
        self.io_type = "Dynamic"
        self.sumo_name = ""
        self.sumo_type = "REAL"
        self.sumo_unit = ""
        self.opc_tag = ""
        self.opc_type = "REAL"
        self.opc_unit = ""
        self.is_array = False
        self.scaling = 1
        self.offset = 0
        self.comment = ""

class VariableEntry:
    def __init__(self):
        self.sumo_name = ""
        self.sumo_type = "REAL"
        self.dimensions = ""
        self.value = 0

class MappingEntry:
    def __init__(self, from_var : str, to_var : str, multi : float):
        self.from_var = from_var
        self.to_var = to_var
        self.multi = multi

def log_print(s : str):
    dt = datetime.datetime.now().strftime("%Y.%m.%d. %H:%M:%S.%f")
    print(f"{dt} {s}")

def convert_to_data(s: str):
    if s == "" or s == None:
        return ""

    if (";" in s):
        result = []
        for item in s.split(";"):
            result.append(convert_to_data(item))
        return result
    try:
        return int(s)
    except:
        try:
            return float(s)
        except ValueError:
            return s

def read_sumocore_xml(file_name: str) -> dict:
    mytree = ET.parse(file_name)
    myroot = mytree.getroot()
    result = {}
    for x in myroot:
        entry = VariableEntry()
        entry.sumo_name = x.attrib["name"]
        entry.sumo_type = x.tag.upper()
        if "dimensions" in x.attrib:
            entry.dimensions = x.attrib["dimensions"]
        entry.value = convert_to_data(x[0].text)
        result[entry.sumo_name] = entry
    return result

def write_sumocore_xml(file_name: str, data: dict):
    with open(file_name, 'w') as file1:
        file1.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        file1.write('<systemstate modelHash="???">\n')
        for y in data:
            x = data[y]
            if x.dimensions != "":
                file1.write(f'    <{x.sumo_type.lower()} name="{x.sumo_name}" dimensions="{x.dimensions}">\n')
            else:
                file1.write(f'    <{x.sumo_type.lower()} name="{x.sumo_name}">\n')
            file1.write(f'        <value>{x.value}</value>\n')
            file1.write(f'    </{x.sumo_type.lower()}>\n')
        file1.write('</systemstate>\n')

def write_sumocore_script(file_name: str, data: dict):
    with open(file_name, 'w') as file1:
        for y in data:
            x = data[y]
            try:
                if x == int(x):
                    x = int(x)
            except:
                pass
            file1.write(f'set {y} {x};\n')

def read_opc_mapping_csv(file_name: str) -> list:
    with open(file_name, 'r') as file1:
        lines = file1.readlines()

    title_row = True
    entries = []
    for line in lines:
        if title_row:
            title_row = False
        else:
            entry = OPCEntry()
            args = line.split(",")
            entry.io = args[0]
            entry.io_type = args[1]
            entry.sumo_name = args[2]
            entry.sumo_type = args[3]
            entry.sumo_unit = args[4]
            entry.opc_tag = args[5]
            entry.opc_type = args[6]
            entry.opc_unit = args[7]
            entry.is_array = (args[8] == "True")
            entry.scaling = convert_to_data(args[9])
            entry.offset = convert_to_data(args[10])
            entry.comment = args[11].strip()
            entries.append(entry)
    return entries

def read_var_mapping_sv(file_name: str, delimiter : str, header_row : bool) -> dict:
    with open(file_name, 'r') as file1:
        lines = file1.readlines()

    title_row = header_row
    entries = {}
    for line in lines:
        if title_row:
            title_row = False
        else:
            args = line.split(delimiter)
            if len(args) == 3:
                entries[args[0]] = MappingEntry(args[0], args[1], float(args[2]))
            elif len(args) == 2:
                entries[args[0]] = MappingEntry(args[0], args[1], 1.0)
            else:
                entries[args[0]] = MappingEntry(args[0], args[0], 1.0)

    return entries

# Generates an array from a flexible (allowing floats) range specification
# The user need to specify, begin and two of end, step and count.
def create_array(begin, end = None, step = None, count = None, includeEnd = True):
    missing = 0
    if (step is None):
        missing += 1
    if (count is None):
        missing += 1
    if (end is None):
        missing += 1
    if (missing < 1):
        raise Exception("Overdefined array. Define one less argument.")
    elif (missing > 1):
        raise Exception("Underdefined array. Define two arguments from end, count and step")

    if (step is None):
        if includeEnd:
            step = (end - begin)/(count - 1)
        else:
            step = (end - begin)/(count)
        return [begin + x * step for x in range(count)]
    elif (count is None):
        count = int((end - begin + step * 0.99)/step)
        if (count < 0):
            step = -step
            count = int((end - begin + step * 0.99)/step)
        result = [begin + x * step for x in range(count)]
        if includeEnd:
            result.append(end)
        return result
    elif (end is None):
        return [begin + x * step for x in range(count)]

    assert False, "create_array reached the end"

def create_temp_folder(base : str):
    characters = 'asdfghjklQWERTYuiop123456789'
    folder = ''.join(random.choice(characters) for _ in range(8))
    folder = os.path.join(base, folder)
    if not os.path.exists(folder):
        os.makedirs(folder)

    return folder

def extract_dll_from_project(project : str, path_to : str):
    with zipfile.ZipFile(project, 'r') as zf:
        with open(path_to, "wb") as f:  # open the output path for writing
             f.write(zf.read("sumoproject.dll"))


def extract_misc_from_project(project : str, what : str, path_to : str):
    with zipfile.ZipFile(project, 'r') as zf:
        with open(path_to, "wb") as f:  # open the output path for writing
             f.write(zf.read(what))

def extract_parameters_from_project(project : str, tsvdir : str, script_to : str, scenario : str = "") -> bool:
    if not os.path.exists(tsvdir):
        os.makedirs(tsvdir)
    par_file = os.path.join(tsvdir, "parameters.txt")
    extract_misc_from_project(project, "parameters.txt", par_file)
    mode = 0
    scenario_column = 1
    columns = []
    with open(par_file, "r") as p, open(script_to, "w") as sw:
        while True:
            line = p.readline().strip()
            if not line:
                break;
            if line == "[CONSTANT INPUT]":
                mode = 0
            elif line == "[DYNAMIC INPUT]":
                mode = 2
            elif mode == 0:
                columns = line.split("\t")
                index = 0
                for l in columns:
                    if l == scenario:
                        scenario_column = index
                    index += 1
                mode = 1
            elif mode == 1:
                cells = line.split("\t")
                if (len(cells) > scenario_column) and (cells[scenario_column] != ""):
                    sw.write(f'set {cells[0]} {cells[scenario_column]};\n')
                else:
                    sw.write(f'set {cells[0]} {cells[1]};\n')
            elif mode == 2:
                cells = line.split("\t")
                tsv_path = os.path.join(tsvdir, cells[0])
                extract_misc_from_project(project, cells[0], tsv_path)
                extras=""
                if cells[1] == "Linear":
                    extras += " -interpolation linear"

                if cells[2] != "N/A":
                    extras += f" -cyclestart 0 -cycletime {cells[2]}"
                sw.write(f'loadtsv "{tsv_path}"{extras};\n')

    return scenario_column != 1 or scenario == ""

def csv_to_tsv(file):
    return _convert_file(file, ".tsv", ",", "\t")

def tsv_to_csv(file):
    return _convert_file(file, ".csv", "\t", ",")

def _convert_file(source_file, dest_ext, source_chr, dest_chr):
    (name, ext) = os.path.splitext(source_file)
    dest_file = name + dest_ext

    with open(source_file, "r") as src, open(dest_file, "w") as dest:
        while True:
            line = src.readline()
            if not line:
                break;
            dest.write(line.replace(source_chr, dest_chr))

    return dest_file

def get_install_location(version):
    import platform
    if platform.system()  == 'Windows':
        import winreg
        aKey = "SOFTWARE\\Dynamita\\" + version +"\\PATHS"
        aReg = winreg.ConnectRegistry(None,winreg.HKEY_CURRENT_USER)
        try:
            aKey = winreg.OpenKey(aReg, aKey)
            val = winreg.QueryValueEx(aKey, "INST")
            return val[0]
        except:
            aKey = "SOFTWARE\\Dynamita\\" + version +"\\PATHS"
            aReg = winreg.ConnectRegistry(None,winreg.HKEY_LOCAL_MACHINE)
            try:
                aKey = winreg.OpenKey(aReg, aKey)
                val = winreg.QueryValueEx(aKey, "INST")
                return val[0]
            except:
                return "" 
    else:
        return ""