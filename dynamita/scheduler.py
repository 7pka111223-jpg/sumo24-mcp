from ctypes import cdll, c_int, c_char_p, CFUNCTYPE
import os
import platform
import sys
import time
import dynamita.tool as dtool

class SumoScheduler:
    def __init__(self, sumoPath=""):
        # Preparing some convenience member fields.
        self.version = 'Sumo24'
        self.platform_name = ''
        self.message_callback = None
        self.datacomm_callback = None
        self.scheduledJobs = 0
        self.install_path = "N/A"
        self.time_in_dc = 0
        self.time_in_msg = 0
        try:
            self._load_sumo(sumoPath)
            self.loading_status = "OK"
        except:
            self.loading_status = "ERROR"
            print("Scheduler: Unable to load Dynamita DTT; check SUMO_INSTALL_DIR and your installation.", file=sys.stderr)
            raise Exception("DTT not found")
        self.jobData = { }
        self.persistent = "persistent"
        self.VERSION = "24.0.0"

        if (self.getDLLVersion() != self.getPYVersion()):
            raise Exception(f"Version mismatch: sumoscheduler.py is version {self.getPYVersion()} but sumoscheduler.dll is {self.getDLLVersion()}")


    def _load_sumo(self, sumoPath=""):
        library_prefix = ''
        library_ext = ''
        self.platform_name = platform.system()
        if self.platform_name == 'Windows':
            library_ext = 'dll'
            library_prefix = ''
            import winreg

            def getInstallLocation():
                aKey = "SOFTWARE\\Dynamita\\" + self.version +"\\PATHS"
                aReg = winreg.ConnectRegistry(None,winreg.HKEY_LOCAL_MACHINE)
                try:
                    aKey = winreg.OpenKey(aReg, aKey)
                    val = winreg.QueryValueEx(aKey, "INST")
                    return val[0]
                except:
                    aKey = "SOFTWARE\\Dynamita\\" + self.version +"\\PATHS"
                    aReg = winreg.ConnectRegistry(None,winreg.HKEY_CURRENT_USER)
                    try:
                        aKey = winreg.OpenKey(aReg, aKey)
                        val = winreg.QueryValueEx(aKey, "INST")
                        return val[0]
                    except:
                        return ""

            if sumoPath == "":
                sumoPath = os.environ.get("SUMO_INSTALL_DIR", "") or getInstallLocation()
            if sumoPath == "":
                raise FileNotFoundError(self.version + 'is not installed')
            if sys.version_info[0] > 3 or (sys.version_info[0] == 3 and sys.version_info[1] >= 8):
                os.add_dll_directory(sumoPath) # Python 3.8
        elif self.platform_name == 'Linux':
            library_ext = 'so'
            library_prefix = 'lib'
        elif self.platform_name == 'Darwin':
            library_ext = 'dylib'
            library_prefix = 'lib'
        else:
            raise NotImplementedError('Unsupported platform.')

        core_filename = os.path.join(
            sumoPath, library_prefix + "sumoscheduler." + library_ext
        )
        if os.path.isfile(core_filename):
            cwd = os.getcwd()
            os.chdir(sumoPath)
            try:
                self._scheduler = cdll.LoadLibrary(core_filename)
            finally:
                os.chdir(cwd)
        else:
            raise FileNotFoundError('Core file not found: ' + core_filename)

        self.install_path = sumoPath

        self._scheduler.schedule.argtypes = [c_char_p, c_char_p, c_char_p, c_int]
        self._scheduler.schedule.restype = c_int
        self._scheduler.setParallelJobs.argtypes = [c_int]
        self._scheduler.setMaxJobReuse.argtypes = [c_int]
        self._scheduler.finish.argtypes = [c_int]
        self._scheduler.sendCommand.argtypes =[c_int, c_char_p]
        self._scheduler.setLogDetails.argtypes = [c_int]
        self._scheduler.getScheduledJobs.restype = c_int
        self._scheduler.getVersion.restype = c_int


        def internal_datacomm_callback(job, msg):
            if self.datacomm_callback is not None:
                start = time.time()
                data = {}
                lst = msg.decode('utf8').split("|")
                for pair in lst:
                    args = pair.split(" = ")
                    data[args[0]] = dtool.convert_to_data(args[1])
                self.datacomm_callback(job, data)
                end = time.time()
                self.time_in_dc += end - start
            return 0


        def internal_message_callback(job, msg):
            if (msg is not None) and (self.message_callback is not None):
                start = time.time()
                self.message_callback(job, msg.decode('utf8'))
                end = time.time()
                self.time_in_msg += end - start
            return 0;


        CALLBACKFUNC = CFUNCTYPE(c_int, c_int, c_char_p)
        self.c_message_callback = CALLBACKFUNC(internal_message_callback)
        self.c_datacomm_callback = CALLBACKFUNC(internal_datacomm_callback)

        self._scheduler.register_message_callback.argtypes = [CALLBACKFUNC]
        self._scheduler.register_message_callback(self.c_message_callback)
        self._scheduler.register_datacomm_callback.argtypes = [CALLBACKFUNC]
        self._scheduler.register_datacomm_callback(self.c_datacomm_callback)


    def schedule (self, model, commands, variables, blockDatacomm=False, jobData=None):
        varstr = "|".join(variables)
        id = self._scheduler.schedule(model.encode("utf8"), (";".join(commands)).encode("utf8"), varstr.encode("utf8"), int(blockDatacomm))
        self.jobData[id] = jobData
        self.scheduledJobs = self._scheduler.getScheduledJobs()
        return id

    def setParallelJobs(self, jobs):
        self._scheduler.setParallelJobs(jobs)


    def setMaxJobReuse(self, reuse):
        self._scheduler.setMaxJobReuse(reuse)


    def finish(self, job):
        self._scheduler.finish(job)
        if (self.jobData[job] == None or not (self.persistent in self.jobData[job]) or  self.jobData[job][self.persistent] != True):
            del self.jobData[job]
        self.scheduledJobs = self._scheduler.getScheduledJobs()

    def deleteJobData(self, job):
        del self.jobData[job]

    def sendCommand(self, job, command):
        self._scheduler.sendCommand(job, command.encode("utf8"))

    def sendCommands(self, job, commands):
        command = ";".join(commands)
        self._scheduler.sendCommand(job, command.encode("utf8"))

    def getJobData(self, jobId):
        return self.jobData[jobId]


    def isSimFinishedMsg(self, msg):
        return msg.startswith("530004")

    def getTimeInPython(self):
        return self.time_in_dc + self.time_in_msg

    def setLogDetails(self, level):
        self._scheduler.setLogDetails(level)

    def getPYVersion(self):
        return self.VERSION

    def getDLLVersion(self):
        v = self._scheduler.getVersion()
        b = v % 1000
        v = int(v/1000)
        m = v % 1000
        v = int(v/1000)
        return f"{v}.{m}.{b}"

    def cleanup(self):
        self.jobData.clear()
        self._scheduler.cleanup()


class _LazyScheduler:
    """Load native code on the first operation, not on tool discovery/import."""
    def __init__(self):
        import threading
        object.__setattr__(self, "_instance", None)
        object.__setattr__(self, "_lock", threading.RLock())

    def _get(self):
        with self._lock:
            if self._instance is None:
                object.__setattr__(self, "_instance", SumoScheduler())
            return self._instance

    def __getattr__(self, name):
        # Saved-project compatibility methods do not need a native runtime.
        if name in ("get", "set", "executeCommand", "getVariableNames"):
            method = getattr(SumoScheduler, name, None)
            if method is not None and method.__module__ == "dynamita_compat":
                return method.__get__(self, type(self))
        return getattr(self._get(), name)

    def __setattr__(self, name, value):
        setattr(self._get(), name, value)

    def cleanup(self):
        with self._lock:
            if self._instance is not None:
                self._instance.cleanup()


sumo = _LazyScheduler()
