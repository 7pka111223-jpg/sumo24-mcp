"""Preflight for SUMO24's Windows native-worker launch requirement."""
import os


def check_native_launch():
    if os.name != "nt":
        return
    import win32api
    import win32job
    if not win32job.IsProcessInJob(win32api.GetCurrentProcess(), None):
        return
    information = win32job.QueryInformationJobObject(None, win32job.JobObjectExtendedLimitInformation)
    flags = information["BasicLimitInformation"]["LimitFlags"]
    allowed = win32job.JOB_OBJECT_LIMIT_BREAKAWAY_OK | win32job.JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK
    if not flags & allowed:
        raise RuntimeError(
            "SUMO24 cannot launch native workers inside this MCP client's Windows Job Object: "
            "the client does not permit process breakaway (native CreateProcess error 5). "
            "Use a client/launcher configured to permit SUMO worker processes. "
            "The server does not change the client's process policy. Changing the SUMO directory "
            "will not fix this client restriction. Offline tools remain available."
        )
