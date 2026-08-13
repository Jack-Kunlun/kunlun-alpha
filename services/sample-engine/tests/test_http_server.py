import json
from urllib.request import urlopen

from ashare_common.health import HealthHandler
from ashare_common.http import ServiceHttpServer


def test_service_http_server_exposes_health_and_metrics() -> None:
    server = ServiceHttpServer("127.0.0.1", 0, HealthHandler("sample"))
    server.start()
    try:
        with urlopen(f"http://127.0.0.1:{server.port}/health") as response:
            body = json.load(response)
            assert body["status"] == "ok"
        with urlopen(f"http://127.0.0.1:{server.port}/metrics") as response:
            assert "kunlun_service_info" in response.read().decode()
    finally:
        server.stop()
