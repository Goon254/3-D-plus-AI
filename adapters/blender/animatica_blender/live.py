# SPDX-License-Identifier: GPL-3.0-or-later
"""Live add-on mode: a socket server in a background thread; batches execute on Blender's main thread."""

from __future__ import annotations

import json
import queue
import socket
import threading

import bpy

from .server import Handler


class LiveServer:
    def __init__(self, port: int = 9876, host: str = "127.0.0.1"):
        self.port, self.host = port, host
        self.handler = Handler()
        self.inbox: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()
        bpy.app.timers.register(self._pump, persistent=True)

    def stop(self) -> None:
        self._stop.set()
        try:
            socket.create_connection((self.host, self.port), timeout=0.5).close()
        except OSError:
            pass

    def _accept_loop(self) -> None:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((self.host, self.port))
        srv.listen(4)
        while not self._stop.is_set():
            conn, _ = srv.accept()
            threading.Thread(target=self._client, args=(conn,), daemon=True).start()
        srv.close()

    def _client(self, conn: socket.socket) -> None:
        with conn, conn.makefile("rw", buffering=1) as f:
            for line in f:
                if not line.strip():
                    continue
                reply: queue.Queue = queue.Queue(maxsize=1)
                self.inbox.put((json.loads(line), reply))
                f.write(json.dumps(reply.get()) + "\n")
                f.flush()

    def _pump(self) -> float | None:
        # main thread: execute queued requests (each batch is one transaction)
        while not self.inbox.empty():
            msg, reply = self.inbox.get_nowait()
            reply.put(self.handler.handle(msg))
        return None if self._stop.is_set() else 0.05
