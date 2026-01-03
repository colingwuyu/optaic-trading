import asyncio

import structlog

from apps.worker.outbox import process_outbox_batch
from libs.core.logging_config import configure_logging
from libs.core.settings import get_settings
from libs.db.session import AsyncSessionLocal


async def worker_loop() -> None:
    settings = get_settings()
    configure_logging(settings)
    logger = structlog.get_logger("worker").bind(app_env=settings.app_env)
    logger.info("worker.startup", log_level=settings.log_level)
    while True:
        processed = 0
        try:
            async with AsyncSessionLocal() as session:
                processed = await process_outbox_batch(session)
        except Exception:
            logger.exception("worker.outbox_failed")
        else:
            logger.info("worker.outbox_processed", count=processed)

        if processed == 0:
            await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(worker_loop())
