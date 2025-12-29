from __future__ import annotations

import asyncio
from typing import Dict, Tuple

from libs.core.settings import get_settings


def _build_s3_client():
    try:
        import boto3
        from botocore.client import Config
    except ImportError as exc:  # pragma: no cover - handled in runtime
        raise RuntimeError("boto3 is required for S3 operations") from exc

    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
        config=Config(signature_version="s3v4"),
    )


async def create_presigned_put(
    *,
    object_key: str,
    content_type: str,
    metadata: Dict[str, str],
    expires_in: int = 900,
) -> Tuple[str, Dict[str, str]]:
    settings = get_settings()
    params = {
        "Bucket": settings.s3_bucket,
        "Key": object_key,
        "ContentType": content_type,
        "Metadata": metadata,
    }
    client = _build_s3_client()
    url = await asyncio.to_thread(
        client.generate_presigned_url,
        "put_object",
        Params=params,
        ExpiresIn=expires_in,
    )
    headers = {"Content-Type": content_type}
    for key, value in metadata.items():
        headers[f"x-amz-meta-{key}"] = value
    return url, headers


async def head_object(object_key: str) -> Dict[str, object]:
    settings = get_settings()
    client = _build_s3_client()
    response = await asyncio.to_thread(
        client.head_object,
        Bucket=settings.s3_bucket,
        Key=object_key,
    )
    etag = response.get("ETag")
    if isinstance(etag, str):
        etag = etag.strip('"')
    return {
        "etag": etag or "",
        "content_length": int(response.get("ContentLength") or 0),
        "content_type": response.get("ContentType") or "",
        "metadata": response.get("Metadata") or {},
    }
