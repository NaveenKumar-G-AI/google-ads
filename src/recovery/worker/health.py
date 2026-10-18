from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import threading
from typing import Any

@dataclass(slots=True)
class WorkerHealthState:
    worker_version: str
    release_id: str
    started_at: str
    startup_complete: bool = False
    stopping: bool = False

    @classmethod
    def create(cls, *, worker_version: str) -> "WorkerHealthState":
        return cls(worker_version=worker_version,release_id=os.environ.get("RECOVERY_RELEASE_ID","unversioned").strip() or "unversioned",started_at=datetime.now(timezone.utc).isoformat())

    def payload(self) -> dict[str, Any]:
        return {"status":"ok" if self.startup_complete and not self.stopping else "starting" if not self.startup_complete else "stopping","startup_complete":self.startup_complete,"stopping":self.stopping,"worker_version":self.worker_version,"release_id":self.release_id,"started_at":self.started_at}

class WorkerHealthServer:
    """Small HTTP surface for Cloud Run Worker Pool startup/liveness checks."""
    def __init__(self, *, state: WorkerHealthState, host: str = "0.0.0.0", port: int = 8080) -> None:
        if not 1 <= port <= 65535: raise ValueError("worker health port must be between 1 and 65535")
        self.state=state; outer=self
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path not in {"/startup","/health"}: self.send_response(404);self.end_headers();return
                code=200 if (outer.state.startup_complete if self.path=="/startup" else outer.state.startup_complete and not outer.state.stopping) else 503
                body=json.dumps(outer.state.payload(),sort_keys=True).encode("utf-8")
                self.send_response(code);self.send_header("Content-Type","application/json");self.send_header("Cache-Control","no-store");self.send_header("Content-Length",str(len(body)));self.end_headers();self.wfile.write(body)
            def log_message(self, format, *args): return
        self.server=ThreadingHTTPServer((host,port),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,name="worker-health",daemon=True)
    def start(self)->None:self.thread.start()
    def close(self)->None:self.server.shutdown();self.server.server_close();self.thread.join(timeout=3)
