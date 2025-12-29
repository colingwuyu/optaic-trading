import asyncio
import os
from datetime import datetime
from uuid import UUID, uuid4

from libs.sdk_py import AsyncPlatformClient


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _fmt_event(event: dict) -> str:
    created = event.get("created_at")
    action = event.get("action")
    resource = event.get("resource", {})
    resource_type = resource.get("resource_type")
    resource_id = resource.get("resource_id")
    actor = event.get("actor", {})
    actor_id = actor.get("principal_id")
    return f"{created} {action} ({resource_type}:{resource_id}) by {actor_id}"


def _filter_notifications(events: list[dict], principal_id: UUID) -> list[dict]:
    inbox = []
    for event in events:
        targets = event.get("targets") or {}
        user_inbox = targets.get("user_inbox") or []
        if str(principal_id) in [str(x) for x in user_inbox]:
            inbox.append(event)
            continue
        if str(event.get("target_principal_id")) == str(principal_id):
            inbox.append(event)
    return inbox


async def main() -> None:
    base_url = os.getenv("API_BASE_URL", "http://localhost:8000")

    tenant_id = uuid4()
    owner_id = uuid4()
    reviewer_id = uuid4()
    agent_id = uuid4()

    async with AsyncPlatformClient(
        base_url, principal_id=owner_id, tenant_id=tenant_id
    ) as client:
        print(f"[{_now()}] Creating tenant...")
        tenant = await client.tenants.create(
            "E2E Demo Tenant", principal_id=owner_id, tenant_id=tenant_id
        )
        root_resource_id = tenant["root_resource_id"]
        print(f"Tenant created: {tenant['id']} root={root_resource_id}")

        print(f"[{_now()}] Creating principals...")
        await client.principals.create(
            "Reviewer User",
            principal_uuid=reviewer_id,
            kind="user",
            principal_id=owner_id,
            tenant_id=tenant_id,
        )
        await client.principals.create(
            "Assistant Agent",
            principal_uuid=agent_id,
            kind="agent",
            principal_id=owner_id,
            tenant_id=tenant_id,
        )

        print(f"[{_now()}] Creating spaces and subspaces...")
        personal_space = await client.resources.create(
            "Space",
            root_resource_id,
            "Personal Space",
            principal_id=owner_id,
            tenant_id=tenant_id,
        )
        personal_subspace = await client.resources.create(
            "Subspace",
            personal_space["id"],
            "Personal Official",
            principal_id=owner_id,
            tenant_id=tenant_id,
        )
        team_space = await client.resources.create(
            "Space",
            root_resource_id,
            "Team Space",
            principal_id=owner_id,
            tenant_id=tenant_id,
        )
        team_subspace = await client.resources.create(
            "Subspace",
            team_space["id"],
            "Team Official",
            principal_id=owner_id,
            tenant_id=tenant_id,
        )
        system_space = await client.resources.create(
            "Space",
            root_resource_id,
            "System Space",
            principal_id=owner_id,
            tenant_id=tenant_id,
        )
        system_subspace = await client.resources.create(
            "Subspace",
            system_space["id"],
            "System Official",
            principal_id=owner_id,
            tenant_id=tenant_id,
        )

        print(f"[{_now()}] Creating project and versioned resources...")
        project = await client.resources.create(
            "Project",
            team_subspace["id"],
            "Roadmap Project",
            principal_id=owner_id,
            tenant_id=tenant_id,
        )
        dataset = await client.resources.create(
            "Dataset",
            project["id"],
            "Core Dataset",
            principal_id=owner_id,
            tenant_id=tenant_id,
        )
        experiment = await client.resources.create(
            "Experiment",
            project["id"],
            "Pricing Experiment",
            principal_id=owner_id,
            tenant_id=tenant_id,
        )
        extension = await client.resources.create(
            "Extension",
            project["id"],
            "Analytics Extension",
            principal_id=owner_id,
            tenant_id=tenant_id,
        )
        print(
            "Created project and versioned resources:",
            project["id"],
            dataset["id"],
            experiment["id"],
            extension["id"],
        )

        print(f"[{_now()}] Granting roles for reviewer and agent...")
        await client.rbac.grant(
            reviewer_id,
            "owner",
            project["id"],
            principal_id=owner_id,
            tenant_id=tenant_id,
        )
        await client.rbac.grant(
            reviewer_id,
            "owner",
            team_subspace["id"],
            principal_id=owner_id,
            tenant_id=tenant_id,
        )
        await client.rbac.grant(
            reviewer_id,
            "owner",
            system_subspace["id"],
            principal_id=owner_id,
            tenant_id=tenant_id,
        )

        team_channel = await client.chat.create_channel(
            project["id"],
            "group",
            "Team Chat",
            principal_id=owner_id,
            tenant_id=tenant_id,
        )
        await client.rbac.grant(
            agent_id,
            "operator",
            team_channel["resource_id"],
            principal_id=owner_id,
            tenant_id=tenant_id,
        )

        print(f"[{_now()}] Posting chat messages...")
        await client.chat.send_message(
            team_channel["resource_id"],
            "Welcome team! @agent please summarize this thread.",
            principal_id=owner_id,
            tenant_id=tenant_id,
        )
        await client.chat.send_message(
            team_channel["resource_id"],
            "Reviewer here, ready to approve.",
            principal_id=reviewer_id,
            tenant_id=tenant_id,
        )

        print(f"[{_now()}] Creating branch + merge request...")
        await client.refs.create_branch(
            project["id"],
            "feature-e2e",
            principal_id=owner_id,
            tenant_id=tenant_id,
        )
        mr = await client.merge_requests.create(
            project["id"],
            "feature-e2e",
            title="E2E merge",
            description="Merge demo branch",
            principal_id=owner_id,
            tenant_id=tenant_id,
        )
        await client.merge_requests.approve(
            mr["id"],
            "approve",
            comment="LGTM",
            principal_id=reviewer_id,
            tenant_id=tenant_id,
        )
        await client.merge_requests.merge(
            mr["id"],
            principal_id=owner_id,
            tenant_id=tenant_id,
        )

        print(f"[{_now()}] Creating promotion request...")
        promo_project = await client.resources.create(
            "Project",
            personal_subspace["id"],
            "Promo Project",
            principal_id=owner_id,
            tenant_id=tenant_id,
        )
        promotion = await client.promotions.create(
            promo_project["id"],
            system_subspace["id"],
            "copy",
            placement={"destination": "system"},
            principal_id=owner_id,
            tenant_id=tenant_id,
        )
        await client.promotions.approve(
            promotion["id"],
            "approve",
            comment="Approved for system",
            principal_id=reviewer_id,
            tenant_id=tenant_id,
        )
        await client.promotions.execute(
            promotion["id"],
            principal_id=owner_id,
            tenant_id=tenant_id,
        )

        print(f"[{_now()}] Recent activities and notifications:")
        for label, principal in [
            ("Owner", owner_id),
            ("Reviewer", reviewer_id),
            ("Agent", agent_id),
        ]:
            events = await client.activities.list(
                principal_id=principal,
                tenant_id=tenant_id,
                limit=30,
            )
            items = events.get("items", [])
            print(f"\n== {label} activities ({len(items)}) ==")
            for event in items[:10]:
                print(_fmt_event(event))

            notifications = _filter_notifications(items, principal)
            print(f"-- {label} notifications ({len(notifications)}) --")
            for event in notifications[:10]:
                print(_fmt_event(event))

    print(f"[{_now()}] E2E demo complete.")


if __name__ == "__main__":
    asyncio.run(main())
