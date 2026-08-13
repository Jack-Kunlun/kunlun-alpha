import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Gauge, generate_latest

from ashare_common.health import HealthHandler


class ServiceHttpServer:
    def __init__(self, host: str, port: int, health: HealthHandler) -> None:
        self._health = health
        self._registry = CollectorRegistry()
        service_info = Gauge(
            "kunlun_service_info",
            "Kunlun service metadata.",
            ["service", "version"],
            registry=self._registry,
        )
        snapshot = health.check()
        service_info.labels(snapshot.service, snapshot.version).set(1)
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                if self.path == "/health":
                    body = owner._health.check().model_dump_json().encode()
                    self.send_response(200)
                    self.send_header("content-type", "application/json; charset=utf-8")
                elif self.path == "/metrics":
                    body = generate_latest(owner._registry)
                    self.send_response(200)
                    self.send_header("content-type", CONTENT_TYPE_LATEST)
                else:
                    body = json.dumps({"error": "not_found"}).encode()
                    self.send_response(404)
                    self.send_header("content-type", "application/json; charset=utf-8")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:  # noqa: A002
                del format, args
                return

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
