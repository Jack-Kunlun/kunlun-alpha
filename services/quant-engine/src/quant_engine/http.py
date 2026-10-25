"""Small internal HTTP boundary for quant-engine paper simulation."""

from __future__ import annotations

import json
import threading
from collections.abc import Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import cast
from urllib.parse import parse_qs, urlsplit

from pydantic import ValidationError

from .paper_workspace import (
    PaperWorkspace,
    PaperWorkspaceConflictError,
    PaperWorkspaceError,
    PaperWorkspaceUnavailableError,
)
from .ranking_store import (
    RankingSnapshotConflictError,
    RankingSnapshotNotFoundError,
    RankingSnapshotStore,
    RankingSnapshotStoreError,
)

MAX_BODY_BYTES = 64 * 1024


class QuantEngineHttpServer:
    def __init__(
        self,
        host: str,
        port: int,
        workspace: PaperWorkspace,
        ranking_store: RankingSnapshotStore | None = None,
    ) -> None:
        owner = self
        self._workspace = workspace
        self._ranking_store = ranking_store or RankingSnapshotStore()

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                request = urlsplit(self.path)
                if request.path == "/health":
                    owner._send(
                        self,
                        200 if owner._workspace.available else 503,
                        {
                            "status": "ok" if owner._workspace.available else "unavailable",
                            "service": "quant-engine",
                        },
                    )
                    return
                if request.path == "/v1/paper/workspace":
                    try:
                        owner._send(self, 200, owner._workspace.snapshot())
                    except PaperWorkspaceUnavailableError:
                        owner._send(self, 503, {"error": "unavailable"})
                    return
                if request.path == "/v1/ranking/snapshots/latest":
                    try:
                        query = parse_qs(request.query, keep_blank_values=True)
                        values = query.get("asOf", [])
                        if len(values) > 1:
                            raise RankingSnapshotStoreError("asOf must appear at most once")
                        owner._send(
                            self,
                            200,
                            owner._ranking_store.latest(values[0] if values else None),
                        )
                    except RankingSnapshotNotFoundError as error:
                        owner._send(self, 404, {"error": "not_found", "message": str(error)})
                    except RankingSnapshotStoreError as error:
                        owner._send(self, 422, {"error": "invalid_request", "message": str(error)})
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
                    if self.path == "/v1/paper/previews":
                        owner._send(self, 200, owner._workspace.preview(body))
                        return
                    if self.path == "/v1/paper/risk-previews":
                        owner._send(self, 200, owner._workspace.risk_preview(body))
                        return
                    if self.path == "/v1/paper/buy-simulations":
                        owner._send(self, 200, owner._workspace.buy_allocation(body))
                        return
                    if self.path == "/v1/ranking/snapshots":
                        owner._send(self, 200, owner._ranking_store.publish(body))
                        return
                    owner._send(self, 404, {"error": "not_found"})
                except PaperWorkspaceUnavailableError:
                    owner._send(self, 503, {"error": "unavailable"})
                except PaperWorkspaceConflictError as error:
                    owner._send(self, 409, {"error": "conflict", "message": str(error)})
                except RankingSnapshotConflictError as error:
                    owner._send(self, 409, {"error": "conflict", "message": str(error)})
                except (
                    PaperWorkspaceError,
                    RankingSnapshotStoreError,
                    ValidationError,
                    ValueError,
                ) as error:
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
