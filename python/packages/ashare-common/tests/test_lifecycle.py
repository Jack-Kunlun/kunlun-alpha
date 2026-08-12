import asyncio
import signal

from ashare_common.lifecycle import ServiceRunner


def test_run_cancels_main_task_and_runs_hooks() -> None:
    runner = ServiceRunner(shutdown_timeout=1.0)
    hook_ran: list[str] = []

    async def hook() -> None:
        hook_ran.append("hook")

    runner.add_shutdown_hook(hook)

    main_started = asyncio.Event()

    async def main() -> None:
        main_started.set()
        await asyncio.Event().wait()  # never returns on its own

    async def scenario() -> None:
        run_task = asyncio.create_task(runner.run(main))
        await asyncio.wait_for(main_started.wait(), timeout=2)
        # Simulate a termination signal once the service is actually running.
        runner._signal_handler(signal.SIGTERM, None)
        await run_task

    asyncio.run(scenario())

    assert main_started.is_set()
    assert runner._running is False
    assert hook_ran == ["hook"]


def test_run_completes_when_stopped_before_main() -> None:
    runner = ServiceRunner(shutdown_timeout=1.0)
    runner._stop_event.set()  # stop before main even starts

    async def main() -> None:
        return None  # completes immediately

    # run() must not hang and must finish cleanly.
    asyncio.run(runner.run(main))
    assert runner._running is False


def test_hook_exception_is_swallowed() -> None:
    """A failing shutdown hook must not prevent the remaining hooks."""
    runner = ServiceRunner(shutdown_timeout=0.5)
    ran: list[str] = []

    async def failing_hook() -> None:
        raise RuntimeError("hook boom")

    async def ok_hook() -> None:
        ran.append("ok")

    runner.add_shutdown_hook(failing_hook)
    runner.add_shutdown_hook(ok_hook)
    runner._stop_event.set()

    async def main() -> None:
        return None

    asyncio.run(runner.run(main))
    assert ran == ["ok"]
