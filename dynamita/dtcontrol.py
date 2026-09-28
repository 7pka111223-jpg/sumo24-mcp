import dynamita.tool as dtool
import dynamita.dmqclient as DMQ
import dynamita.sumogui as SumoGUI
import time
import datetime
import subprocess

class DTTask:
    def __init__(self, action=None, opctag=None, looptime=-1, starttime=-1):
        self.OPCTag = opctag
        self.Action = action
        self.LoopTime = looptime
        self.CurrentTime = starttime

class DTControl:
    
    def __init__(self):
        self.GUI = None
        self.OPC = None
        self.Tick_OPCTag = ""
        self.Tick_NoOPCTime = 1
        self.Tick_Last = ""         
        self.Tick_CheckFrequency = 1
        self.Tick_TickToStep = 1
        self.HeartBeatQueue = None
        self.OPCMapping = None
        self.OPCDataLimits = None
        self.SimulationStep = 60000
        self.LimitTime = 0    
        self.Tasks = []  

        self.OPCTags = []
        self.OPCValues = {}
        self.OPCValues_old = {}
        
        
    def is_opc_time(self):
        return (self.OPC is not None) and (self.Tick_OPCTag != "")
           
    def refresh_opc_values(self):
        if len(self.OPCTags) > 0:
            self.OPCValues_old = self.OPCValues
            self.OPCValues = self.OPC.read_variables(self.OPCTags)              

    def filter_opc_data(self, d: dict, limits: dict) -> dict:
        filtered_d = { }
        for key in d:
            if key in limits:
                min_value = limits[key][0]
                max_value = limits[key][1]
                if d[key] >= min_value and d[key] <= max_value:
                    filtered_d[key] = d[key]
                else:
                    dtool.log_print(f"Value dropped for {key} = {d[key]}. Should be between {min_value} and {max_value}") 
            else:
                dtool.log_print(f"Not limited: {key}")        

        return filtered_d
            
        
    def get_tick(self):
        if self.is_opc_time():
            return self.OPCValues[self.Tick_OPCTag]
        else:
            return datetime.datetime.now()
            
    def did_tick(self):
        t = self.get_tick()
        if self.is_opc_time():
            if t != self.Tick_Last:
                self.Tick_Last = t
                return True
        else:
            if t >= self.Tick_Last + self.Tick_NoOPCTime:
                self.Tick_Last = self.Tick_Last + self.Tick_NoOPCTime
                return True
        return False
        
    def tasks_check_opc(self):
        for t in self.Tasks:
            if t.OPCTag is not None:
                if self.OPCValues[t.OPCTag] != self.OPCValues_old[t.OPCTag]:
                    t.Action(self)
                    
    def tasks_tick(self):
        for t in self.Tasks:
            if t.CurrentTime > 0:
                t.CurrentTime = t.CurrentTime - 1
                if t.CurrentTime <= 0:
                    t.CurrentTime = t.LoopTime
                    t.Action(self)
            
    def run(self):
        self.GUI.push_button("simulate", "start")
        if self.HeartBeatQueue is not None:
            self.HeartBeatQueue.send_data("OK")
        if self.is_opc_time():
            self.OPCTags = [self.Tick_OPCTag]
        for t in self.Tasks:
            if t.OPCTag is not None:
                self.OPCTags.append(t.OPCTag)
        
        self.LimitTime = 0
        self.refresh_opc_values()
        self.Tick_Last = self.get_tick()
        tick = 0
        while self.GUI.is_running():
            if self.HeartBeatQueue is not None:
                self.HeartBeatQueue.send_data("OK")
            self.refresh_opc_values()
            self.tasks_check_opc()
            if self.did_tick():
                tick = tick + 1
                self.tasks_tick()                
                if tick >= self.Tick_TickToStep:
                    tick = 0
                    if self.OPCMapping is not None:
                        opc_data = self.OPC.read_mapped_variables(self.OPCMapping, lambda x: x.io_type == "Dynamic" and x.io == "I")
                        if self.OPCDataLimits is not None:
                            opc_data = self.filter_opc_data(opc_data, self.OPCDataLimits)
                        self.GUI.set_variables(opc_data)

                    self.LimitTime += self.SimulationStep
                    self.GUI.set_variable("Sumo__LimitTime", self.LimitTime)            
                       
            # read all the messages from Sumo
            while self.GUI.communicate():
                # We don't care what they're for now, but this is the place to handle them
                pass
        
            # wait for the next cycle
            time.sleep(self.Tick_CheckFrequency)
        if self.HeartBeatQueue is not None:
            self.HeartBeatQueue.close()
        
    def start_heartbeat(self, key: str):
        self.HeartBeatQueue = DMQ.DMQ.open(key)
        self.HeartBeatQueue.send_data("PATIENCE")
        
    def start_Sumo_GUI(self, project: str, stoptime : str, datacom : str):
        # Start GUI 
        gui = SumoGUI.SumoGUI(project)
        self.GUI = gui
        # Wait for Sumo to load the project. If Sumo is closed before this happens, just exit
        gui.wait_for(lambda: gui.project_loaded == True or gui.is_running() == False)
        if gui.is_running() == False:
            dtool.log_print ("Early exit")
            return
           
        # Go to simulate tab. This will also compile the plant if it's not compiled already (it should be compiled though)
        gui.select_maintab("simulate")
        # Wait for Sumo to compile the model if it's not already compiled. If Sumo is closed before this happens, just exit
        gui.wait_for(lambda: gui.model_initialized == True or gui.is_running() == False)
        if gui.is_running() == False:
            dtool.log_print ("Early exit")
            return

        # Set Sumo__LimitTime to 1. This will stop Sumo from proceeding beyond 1 msec, so we can take over time management
        gui.set_variable("Sumo__LimitTime", 1)

       

        # Set up time constraints and start the simulation
        gui.push_button("simulate", "dynamic_tab")
        gui.push_button("simulate", "stoptime", stoptime)
        gui.push_button("simulate", "datacom", datacom)        
