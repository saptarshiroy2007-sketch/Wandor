"""
File storage abstraction for test documents (locked-doc tests) and any other uploads.

Two backends:
  - "local"  (default): saves to disk under UPLOAD_DIR, served via /uploads static mount.
             Fine for a single-server MVP / dev, NOT fine once you have multiple backend
             instances behind a load balancer (files would only exist on one machine).
  - "s3":    any S3-compatible object storage (AWS S3, Cloudflare R2, Backblaze B2, etc).
             Set STORAGE_BACKEND=s3 and fill in the AWS_* / S3_* env vars.

Swap backends via .env only - routers/uploads.py never needs to change.
"""
import os
import uuid
from pathlib import Path

from ..database import settings

UPLOAD_DIR = Path(settings.upload_dir)


def _local_save(file_bytes: bytes, filename: str) -> str:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    ext = Path(filename).suffix
    safe_name = f"{uuid.uuid4()}{ext}"
    dest = UPLOAD_DIR / safe_name
    with open(dest, "wb") as f:
        f.write(file_bytes)
    # Served by the static mount added in main.py: app.mount("/uploads", ...)
    return f"/uploads/{safe_name}"


def _s3_save(file_bytes: bytes, filename: str) -> str:
    import boto3  # imported lazily so local dev doesn't need boto3 installed

    ext = Path(filename).suffix
    key = f"{uuid.uuid4()}{ext}"

    client = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url or None,  # None = real AWS; set this for R2/B2
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    )
    client.put_object(Bucket=settings.s3_bucket, Key=key, Body=file_bytes)

    if settings.s3_public_base_url:
        return f"{settings.s3_public_base_url.rstrip('/')}/{key}"
    return f"https://{settings.s3_bucket}.s3.amazonaws.com/{key}"


def save_file(file_bytes: bytes, filename: str) -> str:
    """Returns a URL the frontend/Android app can fetch the file from."""
    if settings.storage_backend == "s3":
        return _s3_save(file_bytes, filename)
    return _local_save(file_bytes, filename)
