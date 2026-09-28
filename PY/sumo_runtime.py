"""Single callback owner for every server and tracer job on a scheduler instance."""
import threading
import time

_operation = threading.local()


class Operation:
    """Cancellation owns only jobs started by the current transport operation."""
    def __init__(self):
        self.cancelled = threading.Event()
        self.jobs = []
        self.lock = threading.Lock()

    def cancel(self):
        self.cancelled.set()
        with self.lock:
            for runtime, jid in self.jobs:
                runtime.cancel(jid)

    def attach(self, runtime, jid):
        with self.lock:
            self.jobs.append((runtime, jid))
            if self.cancelled.is_set():
                runtime.cancel(jid)


def run_operation(operation, callback):
    _operation.current = operation
    try:
        if operation.cancelled.is_set():
            raise RuntimeError("Operation cancelled before execution")
        return callback()
    finally:
        _operation.current = None


class Runtime:
    def __init__(self, scheduler, max_rows=100000, max_jobs=128):
        self.scheduler = scheduler
        self.lock = threading.RLock()
        self.schedule_lock = threading.Lock()
        self.jobs = {}
        self.max_rows = max_rows
        self.max_jobs = max_jobs
        self._early = None
        scheduler.message_callback = self._message
        scheduler.datacomm_callback = self._data

    def _event(self, job, kind, payload):
        with self.lock:
            info = self.jobs.get(job)
            if info is None:
                if self._early is not None and len(self._early) < 10000:
                    self._early.append((job, kind, payload))
                return
            if info["status"] in ("finished", "failed", "cancelled", "timed_out"):
                return
            if kind == "data":
                info["rows"].append(dict(payload))
                if len(info["rows"]) > self.max_rows:
                    drop = max(1, self.max_rows // 100)
                    del info["rows"][:drop]
                    info["rows_dropped"] = info.get("rows_dropped", 0) + drop
                    info["rows_truncated"] = True
            else:
                msg = str(payload)
                info["last_msg"] = msg
                info["messages"].append(msg)
                del info["messages"][:-1000]
                if "failed" in msg.lower() or "not valid" in msg.lower():
                    info["error"] = msg
                if self.scheduler.isSimFinishedMsg(msg):
                    info["status"] = "failed" if info["error"] or not info["rows"] else "finished"
                    info["ended"] = True
                    self.scheduler.finish(job)

    def _message(self, job, message):
        self._event(job, "message", message)

    def _data(self, job, data):
        if data:
            self._event(job, "data", data)

    def schedule(self, model, commands, variables, **metadata):
        # Native SUMO can terminate its host on CreateProcess error 5. Check the
        # client's job policy first; never silently change that policy here.
        if type(self.scheduler).__module__ == "dynamita.scheduler":
            from native_launch import check_native_launch
            check_native_launch()
        with self.schedule_lock:
            with self.lock:
                if len(self.jobs) >= self.max_jobs:
                    expired = next((jid for jid, job in self.jobs.items()
                                    if job["status"] not in ("running", "queued")), None)
                    if expired is None:
                        raise RuntimeError("Runtime job capacity reached; finish active jobs before scheduling more")
                    del self.jobs[expired]
                self._early = []
            try:
                jid = self.scheduler.schedule(str(model), commands=commands, variables=variables,
                                              jobData=None)
                with self.lock:
                    if jid < 0:
                        raise RuntimeError(f"Scheduler rejected job: {jid}")
                    self.jobs[jid] = {"status": "running", "rows": [], "messages": [], "error": None,
                                      "ended": False, **metadata}
                    early, self._early = self._early, None
                    for job, kind, value in early:
                        if job == jid:
                            self._event(job, kind, value)
                operation = getattr(_operation, "current", None)
                if operation is not None:
                    operation.attach(self, jid)
                return jid
            finally:
                with self.lock:
                    self._early = None

    def cancel(self, jid, status="cancelled"):
        with self.lock:
            info = self.jobs[jid]
            if info["status"] in ("running", "queued"):
                info["status"] = status
                self.scheduler.finish(jid)

    def wait(self, jid, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self.lock:
                if self.jobs[jid]["status"] not in ("running", "queued"):
                    return self.jobs[jid]
            time.sleep(0.05)
        self.cancel(jid, "timed_out")
        return self.jobs[jid]

    def close(self):
        for jid in list(self.jobs):
            self.cancel(jid)


_runtimes = {}
_lock = threading.Lock()


def get_runtime(scheduler):
    with _lock:
        key = id(scheduler)
        if key not in _runtimes:
            _runtimes[key] = Runtime(scheduler)
        return _runtimes[key]


def close_all():
    with _lock:
        for runtime in _runtimes.values():
            runtime.close()
