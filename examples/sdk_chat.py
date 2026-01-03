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
        tenant = await client.tenants.create("SDK Chat Tenant", tenant_id=tenant_id)
        root_id = tenant["root_resource_id"]
        print("tenant_id:", tenant["id"])

        channel = await client.chat.create_channel(
            parent_id=root_id,
            channel_kind="group",
            name="SDK Chat",
            topic="SDK demo",
        )
        channel_id = channel["resource_id"]
        print("channel_id:", channel_id)

        message = await client.chat.send_message(channel_id, "Hello from the SDK")
        message_id = message["id"]
        print("message_id:", message_id)

        history = await client.chat.list_messages(channel_id, limit=10)
        print("history_count:", len(history["items"]))

        edited = await client.chat.edit_message(
            message_id, "Hello from the SDK (edited)"
        )
        print("edited_at:", edited["edited_at"])

        deleted = await client.chat.delete_message(message_id)
        print("delete_status:", deleted["status"])

        receipt = await client.chat.read_channel(channel_id, message_id)
        print("last_read_message_id:", receipt["last_read_message_id"])

        activities = await client.activities.list(resource_id=channel_id, limit=10)
        print("activity_actions:", [item["action"] for item in activities["items"]])


if __name__ == "__main__":
    asyncio.run(main())
