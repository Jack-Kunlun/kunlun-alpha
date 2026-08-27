"""Small internal HTTP boundary for quant-engine paper simulation."""

from __future__ import annotations

import json
import threading
from collections.abc import Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import cast

from pydantic import ValidationError

from .paper_workspace import PaperWorkspace, PaperWorkspaceConflictError, PaperWorkspaceError

MAX_BODY_BYTES = 64 * 1024


class QuantEngineHttpServer:
    def __init__(self, host: str, port: int, workspace: PaperWorkspace) -> None:
        owner = self
        self._workspace = workspace

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                if self.path == "/health":
                    owner._send(self, 200, {"status": "ok", "service": "quant-engine"})
                    return
                if self.path == "/v1/paper/workspace":
                    owner._send(self, 200, owner._workspace.snapshot())
                    return
                owner._send(self, 404, {"error": "not_found"})

            def do_POST(self) -> None:  # noqa: N802
                try:
                    body = owner._read_json(self)
                    if self.path == "/v1/paper/accounts":
                        owner._send(self, 200, owner._workspace.create_account(body))
                        return
                    if self.path == "/v1/paper/simulations":
                        owner._send(self, 200, owner._workspace.simulate(body))
                        return
                    owner._send(self, 404, {"error": "not_found"})
                except PaperWorkspaceConflictError as error:
                    owner._send(self, 409, {"error": "conflict", "message": str(error)})
                except (PaperWorkspaceError, ValidationError, ValueError) as error:
                    owner._send(self, 422, {"error": "invalid_request", "message": str(error)})

            def log_message(self, format: str, *args: object) -> None:  # noqa: A002
                del format, args

        self._server = ThreadingHTTPServer((host, port), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def port(self) -> int:
        return int(self._server.server_address[1])

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    @staticmethod
    def _read_json(handler: BaseHTTPRequestHandler) -> Mapping[str, object]:
        length_text = handler.headers.get("content-length")
        if length_text is None or not length_text.isdigit():
            raise ValueError("content-length is required")
        length = int(length_text)
        if length <= 0 or length > MAX_BODY_BYTES:
            raise ValueError("request body size is invalid")
        value: object = json.loads(handler.rfile.read(length))
        if not isinstance(value, dict):
            raise ValueError("request body must be a JSON object")
        mapping = cast(dict[object, object], value)
        if not all(isinstance(key, str) for key in mapping):
            raise ValueError("request body must use string keys")
        return {cast(str, key): item for key, item in mapping.items()}

    @staticmethod
    def _send(
        handler: BaseHTTPRequestHandler,
        status: int,
        payload: Mapping[str, object],
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        handler.send_response(status)
        handler.send_header("content-type", "application/json; charset=utf-8")
        handler.send_header("content-length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)
