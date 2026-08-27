"""Process entry point for the internal quant-engine HTTP service."""

from __future__ import annotations

import logging
import os
import signal
import sys
import threading
from types import FrameType

from .http import QuantEngineHttpServer
from .paper_workspace import PaperWorkspace


def main() -> int:
    logging.basicConfig(
        level=os.environ.get("KUNLUN_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    host = os.environ.get("KUNLUN_HOST", "0.0.0.0")
    port = int(os.environ.get("KUNLUN_PORT", "8081"))
    server = QuantEngineHttpServer(host, port, PaperWorkspace())
    stopped = threading.Event()

    def stop(signum: int, frame: FrameType | None) -> None:
        del signum, frame
        stopped.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    server.start()
    logging.getLogger(__name__).info("quant-engine listening on %s:%s", host, server.port)
    try:
        stopped.wait()
    finally:
        server.stop()
    return 0


def main_cli() -> None:
    sys.exit(main())


if __name__ == "__main__":
    main_cli()
