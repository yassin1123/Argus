"""S3-compatible blob storage.

Wired to MinIO in dev (via ARGUS_S3_ENDPOINT=http://minio:9000). The same code
runs against AWS S3 in production by setting ARGUS_S3_ENDPOINT to empty/None
and providing real credentials via IAM role or env.
"""

from __future__ import annotations

import hashlib
import logging
import os
import uuid
from typing import IO, Any

import boto3
from botocore.client import Config as BotoConfig
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# ---- Config -----------------------------------------------------------------

S3_ENDPOINT = (os.getenv("ARGUS_S3_ENDPOINT") or "").strip() or None
# Public-facing endpoint used to SIGN URLs for the browser. Falls back to
# S3_ENDPOINT in production (where the same hostname is reachable).
# Locally, S3_ENDPOINT=http://minio:9000 (Docker DNS) but the browser must hit
# http://localhost:9000 — set ARGUS_S3_PUBLIC_ENDPOINT to that.
S3_PUBLIC_ENDPOINT = (os.getenv("ARGUS_S3_PUBLIC_ENDPOINT") or "").strip() or S3_ENDPOINT
S3_REGION = os.getenv("ARGUS_S3_REGION", "us-east-1")
S3_BUCKET = os.getenv("ARGUS_S3_BUCKET", "argus-sources")
S3_ACCESS_KEY = os.getenv("ARGUS_S3_ACCESS_KEY") or None
S3_SECRET_KEY = os.getenv("ARGUS_S3_SECRET_KEY") or None

# Use path-style addressing for MinIO; AWS S3 supports both.
_BOTO_CONFIG = BotoConfig(
    signature_version="s3v4",
    s3={"addressing_style": "path"},
    retries={"max_attempts": 3, "mode": "standard"},
)


def _client(endpoint: str | None = None):
    """Return a boto3 S3 client. Use endpoint=public for signing browser URLs."""
    return boto3.client(
        "s3",
        endpoint_url=endpoint or S3_ENDPOINT,
        region_name=S3_REGION,
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
        config=_BOTO_CONFIG,
    )


# Two cached clients:
#   _cached_client()         → server-side reads/writes (internal endpoint)
#   _cached_public_client()  → URL signing only (public endpoint)
from functools import lru_cache  # noqa: E402


@lru_cache(maxsize=1)
def _cached_client():
    return _client(S3_ENDPOINT)


@lru_cache(maxsize=1)
def _cached_public_client():
    return _client(S3_PUBLIC_ENDPOINT)


# ---- Bucket bootstrap -------------------------------------------------------


def ensure_bucket() -> None:
    """Create the bucket if it doesn't exist. Idempotent. Safe to call on boot."""
    c = _cached_client()
    try:
        c.head_bucket(Bucket=S3_BUCKET)
        return
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        # 404 / NoSuchBucket → create it. Anything else, re-raise.
        if code not in ("404", "NoSuchBucket", "NotFound"):
            raise
    try:
        # AWS S3 special-cases us-east-1: must NOT pass LocationConstraint.
        if S3_REGION == "us-east-1":
            c.create_bucket(Bucket=S3_BUCKET)
        else:
            c.create_bucket(
                Bucket=S3_BUCKET,
                CreateBucketConfiguration={"LocationConstraint": S3_REGION},
            )
        logger.info("created s3 bucket %s", S3_BUCKET)
    except ClientError as e:
        # Race: another instance created it between head and create.
        if e.response.get("Error", {}).get("Code") in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
            return
        raise


# ---- Read / write -----------------------------------------------------------


def make_blob_key(*, tenant_id: str | None, engagement_id: str, filename: str) -> str:
    """Build a structured S3 key.

    Phase 3 = single tenant, so tenant_id can be None — we still reserve the
    namespace so v1's multi-tenant migration is just a key prefix change.
    """
    tenant = (tenant_id or "default").strip("/") or "default"
    eng = engagement_id.strip("/") or "unknown"
    safe_name = filename.replace("/", "_").replace("\\", "_").strip()
    if not safe_name:
        safe_name = "upload"
    # Add a UUID prefix so re-uploads don't overwrite each other.
    return f"tenants/{tenant}/engagements/{eng}/{uuid.uuid4()}/{safe_name}"


def upload_bytes(
    *,
    key: str,
    body: bytes | IO[bytes],
    content_type: str = "application/octet-stream",
    metadata: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Upload an in-memory blob. Returns {key, size, sha256, content_type}."""
    if isinstance(body, bytes):
        size = len(body)
        sha = hashlib.sha256(body).hexdigest()
        body_io = body
    else:
        # Streaming IO — drain to compute size + hash, then upload.
        # In Phase 3 we accept this overhead; a streaming hash + multipart
        # upload is a worthwhile v1 polish.
        data = body.read()
        size = len(data)
        sha = hashlib.sha256(data).hexdigest()
        body_io = data

    extra: dict[str, Any] = {"ContentType": content_type}
    if metadata:
        extra["Metadata"] = {k: str(v)[:1024] for k, v in metadata.items()}

    _cached_client().put_object(Bucket=S3_BUCKET, Key=key, Body=body_io, **extra)
    return {"key": key, "size": size, "sha256": sha, "content_type": content_type}


def get_signed_url(key: str, *, expires_in: int = 900) -> str:
    """Pre-signed URL valid for `expires_in` seconds (default 15 min).

    Signed against the public-facing endpoint so the browser can use it directly.
    """
    return _cached_public_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": S3_BUCKET, "Key": key},
        ExpiresIn=expires_in,
    )


def get_object_bytes(key: str) -> bytes:
    obj = _cached_client().get_object(Bucket=S3_BUCKET, Key=key)
    return obj["Body"].read()


def delete_blob(key: str) -> None:
    _cached_client().delete_object(Bucket=S3_BUCKET, Key=key)


def stat_blob(key: str) -> dict[str, Any] | None:
    try:
        meta = _cached_client().head_object(Bucket=S3_BUCKET, Key=key)
    except ClientError:
        return None
    return {
        "size": meta.get("ContentLength"),
        "content_type": meta.get("ContentType"),
        "etag": (meta.get("ETag") or "").strip('"'),
        "last_modified": meta.get("LastModified"),
    }
