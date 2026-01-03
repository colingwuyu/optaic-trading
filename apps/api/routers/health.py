from fastapi import APIRouter

from apps.api.schemas import HealthCheck

router = APIRouter(tags=["Health"])


@router.get("/healthz", response_model=HealthCheck)
async def health_check() -> HealthCheck:
    return HealthCheck(ok=True)


@router.get("/")
async def root() -> dict:
    return {"message": "Resource Activity Platform API"}
