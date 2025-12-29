import pytest
from sqlalchemy import text
from libs.db.session import AsyncSessionLocal

@pytest.mark.asyncio
async def test_db_connectivity():
    async with AsyncSessionLocal() as session:
        result = await session.execute(text("SELECT 1"))
        assert result.scalar() == 1

@pytest.mark.asyncio
async def test_tables_exist():
    async with AsyncSessionLocal() as session:
        # Check if tenants table exists
        result = await session.execute(text("SELECT count(*) FROM tenants"))
        assert result.scalar() >= 0
