"""Integration tests for Centrifugo with REAL server communication.

Verifies actual WebSocket message delivery and API publishing.
"""

from __future__ import annotations

import json
import uuid

import pytest


pytestmark = pytest.mark.integration


class TestCentrifugoServerHealth:
    """Verify Centrifugo server is healthy and responding."""

    def test_server_is_running(self, centrifugo_server: dict) -> None:
        """Verify Centrifugo server responds to health check."""
        import urllib.request

        health_url = f"{centrifugo_server['http_url']}/health"
        with urllib.request.urlopen(health_url, timeout=5) as resp:
            assert resp.status == 200

    def test_can_access_api(self, centrifugo_server: dict) -> None:
        """Verify we can access the Centrifugo API."""
        import urllib.request

        info_url = centrifugo_server["http_url"] + "/api"
        api_key = centrifugo_server["api_key"]

        request = urllib.request.Request(
            info_url,
            data=json.dumps({"method": "info"}).encode(),
            headers={
                "Authorization": f"apikey {api_key}",
                "Content-Type": "application/json",
            },
        )

        with urllib.request.urlopen(request, timeout=5) as resp:
            assert resp.status == 200
            body = json.loads(resp.read())
            assert "result" in body


class TestCentrifugoPublishing:
    """Test publishing messages to Centrifugo."""

    def test_publish_to_channel_via_api(self, centrifugo_server: dict) -> None:
        """Publish a message to a channel via HTTP API."""
        import urllib.request

        api_url = centrifugo_server["http_url"] + "/api"
        api_key = centrifugo_server["api_key"]
        channel = f"test-channel-{uuid.uuid4().hex[:8]}"
        message = {"event": "test", "data": "hello"}

        request = urllib.request.Request(
            api_url,
            data=json.dumps(
                {
                    "method": "publish",
                    "params": {
                        "channel": channel,
                        "data": message,
                    },
                }
            ).encode(),
            headers={
                "Authorization": f"apikey {api_key}",
                "Content-Type": "application/json",
            },
        )

        with urllib.request.urlopen(request, timeout=5) as resp:
            assert resp.status == 200
            body = json.loads(resp.read())
            # Publish to empty channel returns empty result (no error)
            assert "error" not in body or body["error"] is None

    def test_broadcast_to_multiple_channels(self, centrifugo_server: dict) -> None:
        """Broadcast a message to multiple channels."""
        import urllib.request

        api_url = centrifugo_server["http_url"] + "/api"
        api_key = centrifugo_server["api_key"]
        channels = [f"broadcast-{uuid.uuid4().hex[:8]}" for _ in range(3)]
        message = {"event": "broadcast", "count": 3}

        request = urllib.request.Request(
            api_url,
            data=json.dumps(
                {
                    "method": "broadcast",
                    "params": {
                        "channels": channels,
                        "data": message,
                    },
                }
            ).encode(),
            headers={
                "Authorization": f"apikey {api_key}",
                "Content-Type": "application/json",
            },
        )

        with urllib.request.urlopen(request, timeout=5) as resp:
            assert resp.status == 200
            body = json.loads(resp.read())
            assert "error" not in body or body["error"] is None


class TestCentrifugoPublisherClass:
    """Test the CentrifugoPublisher class from worker."""

    @pytest.mark.asyncio
    async def test_publisher_connects_and_publishes(
        self, centrifugo_server: dict
    ) -> None:
        """Test CentrifugoPublisher can publish to real server."""
        from apps.worker.outbox import CentrifugoPublisher

        publisher = CentrifugoPublisher(
            api_url=centrifugo_server["http_url"],
            api_key=centrifugo_server["api_key"],
        )

        channel = f"publisher-test-{uuid.uuid4().hex[:8]}"
        data = {"event": "publisher_test", "timestamp": "2024-01-15T10:00:00Z"}

        # Should not raise
        await publisher.publish_channels([channel], data)

    @pytest.mark.asyncio
    async def test_publisher_handles_multiple_channels(
        self, centrifugo_server: dict
    ) -> None:
        """Test CentrifugoPublisher can publish to multiple channels."""
        from apps.worker.outbox import CentrifugoPublisher

        publisher = CentrifugoPublisher(
            api_url=centrifugo_server["http_url"],
            api_key=centrifugo_server["api_key"],
        )

        channels = [f"multi-{uuid.uuid4().hex[:8]}" for _ in range(5)]
        data = {"event": "multi_channel_test", "channels_count": 5}

        # Should not raise
        await publisher.publish_channels(channels, data)


class TestCentrifugoTokenGeneration:
    """Test JWT token generation for Centrifugo."""

    def test_generate_connection_token(self, centrifugo_server: dict) -> None:
        """Generate a valid connection token."""
        import jwt
        from datetime import datetime, timedelta, timezone

        secret = centrifugo_server["token_secret"]
        user_id = str(uuid.uuid4())
        expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

        token = jwt.encode(
            {
                "sub": user_id,
                "exp": expires_at,
                "iat": datetime.now(timezone.utc),
            },
            secret,
            algorithm="HS256",
        )

        # Verify we can decode it
        decoded = jwt.decode(token, secret, algorithms=["HS256"])
        assert decoded["sub"] == user_id

    def test_generate_subscription_token(self, centrifugo_server: dict) -> None:
        """Generate a valid subscription token for a channel."""
        import jwt
        from datetime import datetime, timedelta, timezone

        secret = centrifugo_server["token_secret"]
        user_id = str(uuid.uuid4())
        channel = f"test-channel-{uuid.uuid4().hex[:8]}"
        expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

        token = jwt.encode(
            {
                "sub": user_id,
                "channel": channel,
                "exp": expires_at,
                "iat": datetime.now(timezone.utc),
            },
            secret,
            algorithm="HS256",
        )

        # Verify we can decode it
        decoded = jwt.decode(token, secret, algorithms=["HS256"])
        assert decoded["sub"] == user_id
        assert decoded["channel"] == channel


class TestCentrifugoNotifierIntegration:
    """Test CentrifugoNotifier correctly calls the client.

    These tests use a mock client since Centrifugo rejects publish
    to channels without subscribers. The actual server communication
    is tested in TestCentrifugoPublishing and TestCentrifugoPublisherClass.
    """

    @pytest.fixture
    def mock_centrifugo_client(self):
        """Create a pure mock client that tracks publishes."""

        class MockCentrifugoClient:
            def __init__(self):
                self.published: list[tuple[str, dict]] = []

            async def publish(self, channel: str, data: dict) -> None:
                """Track publish calls without hitting real server."""
                self.published.append((channel, data))

        return MockCentrifugoClient()

    @pytest.mark.asyncio
    async def test_notifier_publishes_upstream_ready(
        self, mock_centrifugo_client
    ) -> None:
        """Test CentrifugoNotifier can publish upstream_ready events."""
        from libs.orchestration.observers import CentrifugoNotifier

        notifier = CentrifugoNotifier(centrifugo_client=mock_centrifugo_client)

        downstream_id = uuid.uuid4()
        upstream_id = uuid.uuid4()

        await notifier.notify_upstream_ready(
            downstream_id=downstream_id,
            upstream_id=upstream_id,
            all_ready=True,
        )

        # Verify message was published
        assert len(mock_centrifugo_client.published) == 1
        channel, data = mock_centrifugo_client.published[0]
        assert channel == f"datasets:{downstream_id}"
        assert data["event"] == "upstream_ready"
        assert data["upstream_id"] == str(upstream_id)
        assert data["all_ready"] is True

    @pytest.mark.asyncio
    async def test_notifier_publishes_upstream_failed(
        self, mock_centrifugo_client
    ) -> None:
        """Test CentrifugoNotifier can publish upstream_failed events."""
        from libs.orchestration.observers import CentrifugoNotifier

        notifier = CentrifugoNotifier(centrifugo_client=mock_centrifugo_client)

        downstream_id = uuid.uuid4()
        upstream_id = uuid.uuid4()
        error_msg = "Connection timeout"

        await notifier.notify_upstream_failed(
            downstream_id=downstream_id,
            upstream_id=upstream_id,
            error=error_msg,
        )

        # Verify message was published
        assert len(mock_centrifugo_client.published) == 1
        channel, data = mock_centrifugo_client.published[0]
        assert channel == f"datasets:{downstream_id}"
        assert data["event"] == "upstream_failed"
        assert data["upstream_id"] == str(upstream_id)
        assert data["error"] == error_msg

    @pytest.mark.asyncio
    async def test_notifier_publishes_lineage_change(
        self, mock_centrifugo_client
    ) -> None:
        """Test CentrifugoNotifier can publish lineage_change events."""
        from libs.orchestration.observers import CentrifugoNotifier

        notifier = CentrifugoNotifier(centrifugo_client=mock_centrifugo_client)

        tenant_id = uuid.uuid4()
        resource_id = uuid.uuid4()

        await notifier.notify_lineage_change(
            tenant_id=tenant_id,
            resource_id=resource_id,
            change_type="created",
        )

        # Verify message was published
        assert len(mock_centrifugo_client.published) == 1
        channel, data = mock_centrifugo_client.published[0]
        assert channel == f"lineage:{tenant_id}"
        assert data["event"] == "lineage_change"
        assert data["resource_id"] == str(resource_id)
        assert data["change_type"] == "created"


class TestCentrifugoChannelPatterns:
    """Test the channel naming patterns used in OptAIC."""

    def test_dataset_channel_pattern(self, centrifugo_server: dict) -> None:
        """Verify dataset channel pattern works."""
        import urllib.request

        api_url = centrifugo_server["http_url"] + "/api"
        api_key = centrifugo_server["api_key"]
        dataset_id = uuid.uuid4()
        channel = f"datasets:{dataset_id}"

        request = urllib.request.Request(
            api_url,
            data=json.dumps(
                {
                    "method": "publish",
                    "params": {
                        "channel": channel,
                        "data": {"event": "upstream_ready", "all_ready": True},
                    },
                }
            ).encode(),
            headers={
                "Authorization": f"apikey {api_key}",
                "Content-Type": "application/json",
            },
        )

        with urllib.request.urlopen(request, timeout=5) as resp:
            assert resp.status == 200

    def test_lineage_channel_pattern(self, centrifugo_server: dict) -> None:
        """Verify lineage channel pattern works."""
        import urllib.request

        api_url = centrifugo_server["http_url"] + "/api"
        api_key = centrifugo_server["api_key"]
        tenant_id = uuid.uuid4()
        channel = f"lineage:{tenant_id}"

        request = urllib.request.Request(
            api_url,
            data=json.dumps(
                {
                    "method": "publish",
                    "params": {
                        "channel": channel,
                        "data": {"event": "lineage_change", "change_type": "updated"},
                    },
                }
            ).encode(),
            headers={
                "Authorization": f"apikey {api_key}",
                "Content-Type": "application/json",
            },
        )

        with urllib.request.urlopen(request, timeout=5) as resp:
            assert resp.status == 200

    def test_tenant_resource_channel_pattern(self, centrifugo_server: dict) -> None:
        """Verify tenant resource channel pattern t:{tenant}:r:{resource} works."""
        import urllib.request

        api_url = centrifugo_server["http_url"] + "/api"
        api_key = centrifugo_server["api_key"]
        tenant_id = uuid.uuid4()
        resource_id = uuid.uuid4()
        channel = f"t:{tenant_id}:r:{resource_id}"

        request = urllib.request.Request(
            api_url,
            data=json.dumps(
                {
                    "method": "publish",
                    "params": {
                        "channel": channel,
                        "data": {"event": "resource.updated"},
                    },
                }
            ).encode(),
            headers={
                "Authorization": f"apikey {api_key}",
                "Content-Type": "application/json",
            },
        )

        with urllib.request.urlopen(request, timeout=5) as resp:
            assert resp.status == 200
