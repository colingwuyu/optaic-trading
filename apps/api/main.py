from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import FileResponse
from starlette.staticfiles import StaticFiles

from apps.api.routers.activities import router as activities_router
from apps.api.routers.attachments import router as attachments_router
from apps.api.routers.chat import router as chat_router
from apps.api.routers.datasets import router as datasets_router
from apps.api.routers.experiments import router as experiments_router
from apps.api.routers.guardrails import router as guardrails_router
from apps.api.routers.health import router as health_router
from apps.api.routers.merge_requests import router as merge_requests_router
from apps.api.routers.ops import router as ops_router
from apps.api.routers.pipelines import router as pipelines_router
from apps.api.routers.principals import router as principals_router
from apps.api.routers.promotions import router as promotions_router
from apps.api.routers.realtime import router as realtime_router
from apps.api.routers.rbac import router as rbac_router
from apps.api.routers.refs import router as refs_router
from apps.api.routers.resources import router as resources_router
from apps.api.routers.signals import router as signals_router
from apps.api.routers.subscriptions import router as subscriptions_router
from apps.api.routers.system import router as system_router
from apps.api.routers.tenants import router as tenants_router
from libs.core.logging_config import configure_logging
from libs.core.settings import get_settings

tags_metadata = [
    {"name": "Health", "description": "Service health checks."},
    {"name": "Tenants", "description": "Development-only tenant utilities."},
    {"name": "Principals", "description": "Development-only principal utilities."},
    {"name": "Resources", "description": "Resource CRUD, moves, and child listings."},
    {"name": "RBAC", "description": "Role bindings and effective permissions."},
    {"name": "Activities", "description": "Activity feed filtered by RBAC."},
    {"name": "Attachments", "description": "Attachment upload and finalize."},
    {"name": "Chat", "description": "Channels, messages, and read receipts."},
    {"name": "Realtime", "description": "Centrifugo token issuance."},
    {"name": "Refs", "description": "Branch and ref operations."},
    {"name": "MergeRequests", "description": "Merge request workflows."},
    {"name": "Promotions", "description": "Promotion requests and execution."},
    {"name": "Subscriptions", "description": "Resource subscriptions."},
    {"name": "System", "description": "System upgrades and runtime info."},
    # Quant Domain
    {"name": "Datasets", "description": "Dataset preview, status, and refresh."},
    {"name": "Signals", "description": "Signal registration, validation, and promotion."},
    {"name": "Operators", "description": "Expression operators and evaluation."},
    {"name": "Experiments", "description": "Expression experiments and macros."},
    {"name": "Pipelines", "description": "Pipeline definitions, instances, and runs."},
]

@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings)
    logger = structlog.get_logger("api").bind(app_env=settings.app_env)
    logger.info("api.startup", log_level=settings.log_level)

    # Run startup hooks (seed definitions, etc.)
    try:
        from libs.core.startup import run_startup_hooks
        await run_startup_hooks()
    except Exception as e:
        logger.warning("api.startup_hooks_failed", error=str(e))

    yield
    logger.info("api.shutdown")

app = FastAPI(
    title="Resource Activity Platform API",
    openapi_tags=tags_metadata,
    lifespan=lifespan,
)

class SPAStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404 and "." not in Path(path).name:
                index_path = Path(self.directory) / "index.html"
                if index_path.exists():
                    return FileResponse(index_path)
            raise


def _get_webui_dist() -> Path | None:
    try:
        import optaic
    except Exception:
        return None
    return Path(optaic.__file__).resolve().parent / "webui_dist"

settings = get_settings()
origins = [origin.strip() for origin in settings.cors_allow_origins.split(",") if origin.strip()]
allow_origins = ["*"] if "*" in origins else origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins or ["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(tenants_router)
app.include_router(principals_router)
app.include_router(resources_router)
app.include_router(rbac_router)
app.include_router(activities_router)
app.include_router(attachments_router)
app.include_router(chat_router)
app.include_router(guardrails_router)
app.include_router(realtime_router)
app.include_router(refs_router)
app.include_router(merge_requests_router)
app.include_router(promotions_router)
app.include_router(subscriptions_router)
app.include_router(system_router)
# Quant Domain routers
app.include_router(datasets_router)
app.include_router(signals_router)
app.include_router(ops_router)
app.include_router(experiments_router)
app.include_router(pipelines_router)

webui_dist = _get_webui_dist()
if webui_dist and webui_dist.is_dir():
    app.mount("/", SPAStaticFiles(directory=str(webui_dist), html=True), name="webui")
