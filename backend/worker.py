"""Accord durable-job worker entrypoint (ADR 0010).

Runnable from the ``backend/`` directory as::

    python worker.py
    python -m worker
"""

from __future__ import annotations

import asyncio
import contextlib
import signal

import structlog

from app.config import get_settings
from app.db import configure_engine, dispose_engine, get_session_factory
from app.jobs.handlers import registry
from app.jobs.worker import WorkerLoop
from app.logging_config import configure_logging

logger = structlog.get_logger(__name__)


async def _run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    configure_engine()

    worker = WorkerLoop(get_session_factory(), registry)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, worker.request_shutdown)

    logger.info("worker_entrypoint_starting", worker_id=worker.worker_id)
    try:
        await worker.run()
    finally:
        await dispose_engine()
        logger.info("worker_entrypoint_exited", worker_id=worker.worker_id)


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
