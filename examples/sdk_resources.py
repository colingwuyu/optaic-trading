import asyncio
import os
import uuid

from libs.sdk_py.client import AsyncPlatformClient


async def main() -> None:
    base_url = os.getenv("API_BASE_URL", "http://localhost:8000")
    principal_id = uuid.uuid4()
    tenant_id = uuid.uuid4()

    async with AsyncPlatformClient(
        base_url, principal_id=principal_id, tenant_id=tenant_id
    ) as client:
        health = await client.health.get()
        print("health:", health)

        tenant = await client.tenants.create("SDK Demo Tenant", tenant_id=tenant_id)
        root_id = tenant["root_resource_id"]
        print("tenant_id:", tenant["id"])

        project = await client.resources.create(
            "Project",
            root_id,
            "SDK Project",
            metadata={"source": "sdk"},
        )
        print("project_id:", project["id"])

        await client.resources.create(
            "Doc",
            project["id"],
            "SDK Spec",
        )

        children = await client.resources.list_children(project["id"], limit=10)
        print("children_count:", len(children["items"]))

        updated = await client.resources.update(
            project["id"], name="SDK Project Updated"
        )
        print("updated_name:", updated["name"])

        effective = await client.rbac.effective(project["id"])
        print("permissions_count:", len(effective["permissions"]))

        activities = await client.activities.list(resource_id=project["id"], limit=5)
        print("activity_actions:", [item["action"] for item in activities["items"]])


if __name__ == "__main__":
    asyncio.run(main())
