import logging
import sys


def setup_logging(service_name: str, level: str = "INFO") -> None:
    """Configure structured logging for a service.

    Outputs JSON-formatted log lines to stdout.
    """
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            '{"ts":"%(asctime)s","level":"%(levelname)s","svc":"'
            + service_name
            + '","msg":"%(message)s"}',
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )
    root.handlers.clear()
    root.addHandler(handler)
