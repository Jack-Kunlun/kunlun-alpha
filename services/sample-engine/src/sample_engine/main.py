import asyncio
import logging
import sys

from ashare_common import HealthHandler, ServiceConfig, ServiceRunner, setup_logging


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

    logger = logging.getLogger(__name__)
    logger.info("Starting service %s", config.service_name)

    health = HealthHandler(service=config.service_name)
    logger.info("Health check ready: %s", health.check().model_dump())

    runner = ServiceRunner(shutdown_timeout=config.shutdown_timeout_seconds)
    asyncio.run(runner.run(lambda: run_engine(config, health)))


def main_cli() -> None:
    sys.exit(main())
