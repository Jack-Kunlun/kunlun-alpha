import asyncio
import contextlib
import logging
import signal
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any

logger = logging.getLogger(__name__)

ShutdownHook = Callable[[], Awaitable[Any]]


class ServiceRunner:
    """Lifecycle manager for a long-running service.

    Handles signal registration, startup, and graceful shutdown.
    Uses signal.signal() for cross-platform compatibility (Windows included).
    """

    def __init__(self, shutdown_timeout: float = 10.0) -> None:
        self._shutdown_timeout = shutdown_timeout
        self._stop_event = asyncio.Event()
        self._shutdown_hooks: list[ShutdownHook] = []
        self._running = False

    def _signal_handler(self, signum: int, _frame: object) -> None:
        logger.info("Received termination signal %s", signum)
        self._stop_event.set()

    def add_shutdown_hook(self, hook: ShutdownHook) -> None:
        self._shutdown_hooks.append(hook)

    async def run(self, main: Callable[[], Coroutine[Any, Any, Any]]) -> None:
        """Run the service until a termination signal is received."""
        self._running = True

        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, self._signal_handler)

        logger.info("Service started, waiting for termination signal")
        main_task = asyncio.create_task(main())

        await self._stop_event.wait()
        logger.info("Shutdown signal received, stopping...")
        self._running = False

        if not main_task.done():
            main_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await main_task

        await self._run_hooks()
        logger.info("Shutdown complete")

    async def _run_hooks(self) -> None:
        for hook in self._shutdown_hooks:
            try:
                await asyncio.wait_for(hook(), timeout=self._shutdown_timeout)
            except Exception:
                logger.exception("Shutdown hook failed")
