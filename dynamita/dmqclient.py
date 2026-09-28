from ctypes import cdll, c_int, c_char_p, CFUNCTYPE
import platform
import sys
import os
import threading
import time
import datetime
import subprocess
import random
import codecs

from . import tool as dtool

if platform.system() == 'Windows':  
    import winreg
          
class DMQClient:
    pass

class DMQDllWrapper:
    def __init__(self):
        self.version = 'Sumo24'
        self.platform_name = '' 
        self.install_path = ""
        self.sumo_path = ""
        self.license_file = ""
        self._load_sumo()
        
    def _check_dmq(self):
        if self.platform_name == 'Windows':
            msg = subprocess.check_output(["tasklist","/fi", "ImageName eq dmq.exe"])
            msg = codecs.decode(msg, 'unicode_escape')
            last_line = msg.strip().split('\r\n')[-1]
            return last_line.lower().startswith("dmq.exe")
        return False
    
    def start_dmq(self):
        dt = datetime.datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
        if not os.path.exists("dmq_logs"):
            os.makedirs("dmq_logs")
        with open(f'dmq_logs/dmq{dt}.bat', 'w') as f:
            f.write("@echo off\n")
            f.write(f'"{self.install_path}/DMQ.exe" -autoexit" >dmq_logs/dmq{dt}.log\n')
        
        subprocess.Popen([f"dmq_logs\\dmq{dt}.bat"])
        time.sleep(1)
    
    def _load_sumo(self):
        library_prefix = ''
        library_ext = ''
        self.platform_name = platform.system()
        if self.platform_name == 'Windows':
            library_ext = 'dll'
            library_prefix = ''
            
                        
            self.sumo_path = self.install_path = self.get_install_location()                       
            
            if self.install_path == "":
                raise FileNotFoundError(self.version + ' is not installed')
                
            self.license_file = self.get_license_location()
            if self.license_file == "":
                raise FileNotFoundError(self.version + ' has no license')
                
                
            if not self._check_dmq():
                self.start_dmq()
                
            if sys.version_info[0] > 3 or (sys.version_info[0] == 3 and sys.version_info[1] >= 8):
                os.add_dll_directory(self.install_path) # Python 3.8
        # elif self.platform_name == 'Linux':
            # library_ext = 'so'
            # library_prefix = 'lib'
        # elif self.platform_name == 'Darwin':
            # library_ext = 'dylib'
            # library_prefix = 'lib'
        else:
            raise NotImplementedError('Unsupported platform: '+self.platform_name)

        dmqClient_filename = os.path.join(
            self.install_path, library_prefix + "DMQClient." + library_ext
        )
        if os.path.isfile(dmqClient_filename):
            cwd = os.getcwd()
            os.chdir(self.install_path)
            # load DMQClient.dll from install
            self.dmq_dll = cdll.LoadLibrary(dmqClient_filename)
            os.chdir(cwd)
        else:
            raise FileNotFoundError('DMQClient file not found: ' + dmqClient_filename)
        
        self.dmq_dll.initModule.argtypes = [c_char_p]         
        self.dmq_dll.createQueue.argtypes = []   
        self.dmq_dll.createQueue.restype = c_char_p        
        self.dmq_dll.createSpecQueue.argtypes = [c_char_p]
        self.dmq_dll.createSpecQueue.restype = c_char_p
        self.dmq_dll.openQueue.argtypes = [c_char_p] 
        self.dmq_dll.openQueue.restype = c_char_p
        self.dmq_dll.sendText.argtypes = [c_char_p, c_char_p] 
        self.dmq_dll.sendText.restype = c_int
        self.dmq_dll.getText.argtypes = [c_char_p, c_int]                
        self.dmq_dll.getText.restype = c_char_p
        self.dmq_dll.closeQueue.argtypes = [c_char_p] 
        self.dmq_dll.getVersion.restype = c_int
        self.dmq_dll.applyLicense.argtypes = [c_char_p]
        self.dmq_dll.applyLicense.restype = c_char_p

        # call initModule("Python") from the dll
        self.dmq_dll.initModule("Python".encode("utf8"))
    
    if platform.system() == 'Windows':    
        def get_license_location(self):
            aKey = "SOFTWARE\\Dynamita\\" + self.version +"\\PATHS"
            aReg = winreg.ConnectRegistry(None,winreg.HKEY_CURRENT_USER)
            try:
                aKey = winreg.OpenKey(aReg, aKey)
                val = winreg.QueryValueEx(aKey, "License")
                return val[0]
            except:
                return ""
                
        def get_install_location(self):
            aKey = "SOFTWARE\\Dynamita\\" + self.version +"\\PATHS"
            aReg = winreg.ConnectRegistry(None,winreg.HKEY_CURRENT_USER)
            try:
                aKey = winreg.OpenKey(aReg, aKey)
                val = winreg.QueryValueEx(aKey, "INST")
                return val[0]
            except:
                aKey = "SOFTWARE\\Dynamita\\" + self.version +"\\PATHS"
                aReg = winreg.ConnectRegistry(None,winreg.HKEY_LOCAL_MACHINE)
                try:
                    aKey = winreg.OpenKey(aReg, aKey)
                    val = winreg.QueryValueEx(aKey, "INST")
                    return val[0]
                except:
                    return ""

    def setModuleName(self, name):
        self.dmq_dll.initModule(name.encode("utf8"))
    
    def create(self):
        dmqc = DMQClient()
        dmqc.dmq_dll = self
        dmqc.key_p = self.dmq_dll.createQueue()
        dmqc.key = dmqc.key_p.decode('utf8')
        return dmqc
        
    def create_specific_queue(self, key: str) -> DMQClient:
        dmqc = DMQClient()
        dmqc.dmq_dll = self
        dmqc.key_p = self.dmq_dll.createSpecQueue(key.encode("utf8"))
        dmqc.key = dmqc.key_p.decode('utf8')
        return dmqc
        
    def open(self, key: str) -> DMQClient:
        dmqc = DMQClient()
        dmqc.dmq_dll = self
        dmqc.key_p = self.dmq_dll.openQueue(key.encode("utf8"))
        dmqc.key = dmqc.key_p.decode('utf8')
        return dmqc
           
    def apply_new_license(self):
        self.license_file = self.get_license_location()
        if self.license_file == "":
            raise FileNotFoundError(self.version + ' has no license')
        return self.dmq_dll.applyLicense(self.license_file.encode("utf8")).decode("utf8")

            
DMQ = DMQDllWrapper()

class DMQClient:
    def __init__(self):       
        self.key = "N/A"
        self.key_p = None
        
    def send_data(self, msg: str):
        return DMQ.dmq_dll.sendText(self.key_p, msg.encode("utf8"))
    
    def read_data(self, blocking: bool = False):
        blocking_int = 0
        if blocking:
            blocking_int = 1
        ptr = DMQ.dmq_dll.getText(self.key_p, blocking_int)
        result = ptr.decode("utf8")
        return result
        
    def close(self):
        DMQ.dmq_dll.closeQueue(self.key_p)
        self.key_p = None
        self.key = ""
           

class OPCClient:    
    def __init__(self, address: str, config: str):        
        self.lock = threading.Lock()        
        self.address = [address]
        self.config = config        
        self.reconnect()
        
    def add_backup_address(self, address):
        self.address.append(address)

    def reconnect(self, index = 0):
        self.closed = False
        self.dmq = DMQ.create()
        dt = datetime.datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
        if not os.path.exists("dmq_logs"):
            os.makedirs("dmq_logs")
        batch = f'dmq_logs\\opc{dt}_{random.randint(1, 999999)}.bat'
        # self.process = subprocess.Popen([f"{DMQ.install_path}/OPCClient.exe", address, config, self.dmq.key])
        dtool.log_print(f"Connecting to {self.address[index]}")
        with open(batch, 'w') as f:
            f.write("@echo off\n")
            f.write(f'"{DMQ.install_path}/OPCClient.exe" "{self.address[index]}" "{self.config}" "{self.dmq.key}" >"{batch}.out" 2>"{batch}.err"')
        
        self.process = subprocess.Popen([batch])
        
    def is_running(self):
        return (not self.closed) and (self.process.poll() is None)
        
    def read_variables(self, variables: list) -> dict:
        self.lock.acquire()
        self.dmq.send_data(f"read ,{','.join(variables)}")
        res = {}
        line = self.dmq.read_data(True)
        retries = 0
        max_retries = len(self.address)
        while line != "ReadEnd":
            if self.closed or line == "CLOSED":
                self.closed = True
                if retries < max_retries:
                    dtool.log_print(f"Reconnecting to OPC when reading variables {variables}")                    
                    self.reconnect(retries)
                    retries = retries + 1
                    self.dmq.send_data(f"read ,{','.join(variables)}")
                    res = {}
                    line = self.dmq.read_data(True)
                    continue
                else:
                    dtool.log_print(f"Reconnecting to OPC failed")
                    break
            if line == "":
                dtool.log_print("ERROR in read_variables response: Empty Response")
                break
            args = line.split("|")
            if (len(args) >= 2):
                res[args[0]] = dtool.convert_to_data((args[1].split("="))[1])
            else:
                dtool.log_print(f"ERROR in read_variables response: {line}")
                break
            line = self.dmq.read_data(True)
        self.lock.release()
        return res
        
    def write_variables(self, variables: dict) -> dict:
        self.lock.acquire()
        a = []
        for key in variables:
            a.append(f"{key}={variables[key]}")
        self.dmq.send_data(f"write ,{','.join(a)}")
        res = {}
        retries = 0
        max_retries = len(self.address)
        line = self.dmq.read_data(True)
        while line != "WriteEnd":
            if self.closed or line == "CLOSED":
                self.closed = True
                if retries < max_retries:
                    dtool.log_print(f"Reconnecting to OPC when writing variables {variables}")                    
                    self.reconnect(retries)
                    retries = retries + 1
                    self.dmq.send_data(f"write ,{','.join(a)}")
                    res = {}
                    line = self.dmq.read_data(True)
                    continue
                else:
                    dtool.log_print(f"Reconnecting to OPC failed")
                    break
            args = line.split("|")
            if (len(args) >= 2):
                res[args[0]] = dtool.convert_to_data((args[1].split("="))[1])
            else:
                dtool.log_print(f"ERROR in write_variables response: {line}")
                break
            line = self.dmq.read_data(True)  
        self.lock.release()
        return res
    
    def read_mapped_variables(self, mapped_variables: list, condition):
        lst = []
        result = {}
        for x in mapped_variables:
            if condition(x):
                lst.append(x.opc_tag)
        data = self.read_variables(lst)
        for x in mapped_variables:
            if condition(x):
                if x.sumo_type == "REAL":
                    result[x.sumo_name] = data[x.opc_tag] / x.scaling - x.offset
                elif x.sumo_type == "INT":
                    result[x.sumo_name] = int(data[x.opc_tag] / x.scaling - x.offset)
                else:
                    result[x.sumo_name] = data[x.opc_tag]
        return result
    
    def write_mapped_variables(self, mapped_variables: list, condition, values: dict):
        data = {}
        result = {}
        for x in mapped_variables:
            if condition(x):                
                if x.sumo_type == "REAL":
                    data[x.opc_tag] = (values[x.sumo_name].value + x.offset) * x.scaling
                elif x.sumo_type == "INT":
                    data[x.opc_tag] = int((values[x.sumo_name].value + x.offset) * x.scaling)
                else:
                    data[x.opc_tag] = values[x.sumo_name].value
        result = self.write_variables(data)
        return result
                
    def close(self):
        self.lock.acquire()
        self.dmq.close()
        self.lock.release()
