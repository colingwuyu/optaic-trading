import asyncio

import structlog

from apps.agent.runner import AgentRunner
from libs.core.logging_config import configure_logging
from libs.core.settings import get_settings


async def agent_loop() -> None:
    settings = get_settings()
    configure_logging(settings)
    logger = structlog.get_logger("agent").bind(app_env=settings.app_env)
    runner = AgentRunner(
        api_base_url=settings.agent_api_base_url,
        model=settings.agent_model,
        batch_size=settings.agent_batch_size,
    )
    logger.info("agent.startup", log_level=settings.log_level)
    while True:
        try:
            result = await runner.run_once()
            logger.info(
                "agent.cycle",
                processed=result.processed,
                responded=result.responded,
            )
        except Exception:
            logger.exception("agent.loop_failed")
        await asyncio.sleep(settings.agent_poll_interval)


if __name__ == "__main__":
    asyncio.run(agent_loop())
