import socket
import threading
import time

import uvicorn
from runai_orch.adapters.mock import MockHAdapter
from runai_orch.app import create_app
from runai_orch.orchestrator import Orchestrator


class LiveServer:
    """uvicorn dans un thread : vrai HTTP + vrai SSE (httpx ASGITransport bufferise les reponses)."""

    def __init__(self, adapter: MockHAdapter, poll_s: float = 0.05):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        self.port = s.getsockname()[1]
        s.close()
        self.orch = Orchestrator(adapter, poll_s=poll_s)
        self.app = create_app(self.orch)
        self.server = uvicorn.Server(uvicorn.Config(self.app, host="127.0.0.1", port=self.port, log_level="warning"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.url = f"http://127.0.0.1:{self.port}"

    def __enter__(self):
        self.thread.start()
        while not self.server.started:
            time.sleep(0.01)
        return self

    def __exit__(self, *exc):
        self.server.should_exit = True
        self.thread.join(10)
