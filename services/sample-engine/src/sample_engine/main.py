import asyncio
import logging
import sys
from collections.abc import Awaitable, Callable

from ashare_common import (
    HealthHandler,
    ServiceConfig,
    ServiceHttpServer,
    ServiceRunner,
    init_telemetry,
    setup_logging,
)


async def run_engine(config: ServiceConfig, health: HealthHandler) -> None:
    """Simulated engine work loop."""
    logger = logging.getLogger(__name__)
    logger.info("Engine started, service=%s port=%s", config.service_name, config.port)

    while True:
        logger.info("Engine heartbeat, health=%s", health.check().status)
        await asyncio.sleep(30)


def main() -> None:
    config = ServiceConfig()
    setup_logging(config.service_name, config.log_level)
    telemetry = init_telemetry(config.service_name)

    logger = logging.getLogger(__name__)
    logger.info("Starting service %s", config.service_name)

    health = HealthHandler(service=config.service_name)
    http_server = ServiceHttpServer(config.host, config.port, health)
    http_server.start()
    logger.info("Health check ready: %s", health.check().model_dump())

    runner = ServiceRunner(shutdown_timeout=config.shutdown_timeout_seconds)
    runner.add_shutdown_hook(_async_hook(http_server.stop))
    runner.add_shutdown_hook(_async_hook(telemetry.shutdown))
    asyncio.run(runner.run(lambda: run_engine(config, health)))


def _async_hook(callback: Callable[[], None]) -> Callable[[], Awaitable[None]]:
    async def hook() -> None:
        await asyncio.to_thread(callback)

    return hook


def main_cli() -> None:
    sys.exit(main())
