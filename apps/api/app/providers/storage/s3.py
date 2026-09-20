from __future__ import annotations

import secrets

from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

from app.config import get_settings

from .base import StorageObjectNotFound, StorageProvider


def _is_not_found(exc: ClientError) -> bool:
    code = (getattr(exc, "response", None) or {}).get("Error", {}).get("Code", "")
    return code in {"404", "NoSuchKey", "NotFound"}


class S3Storage(StorageProvider):
    """Private S3-compatible object storage (AWS S3, MinIO, R2, ...).

    The provider never falls back to the local filesystem: a production storage
    failure must surface as an explicit error.
    """

    def __init__(
        self,
        client=None,
        *,
        bucket: str | None = None,
        prefix: str | None = None,
    ):
        settings = get_settings()
        self.bucket = (bucket if bucket is not None else settings.s3_bucket).strip()
        if not self.bucket:
            raise RuntimeError("S3_BUCKET 未配置，无法启用对象存储。")
        self.prefix = (
            prefix if prefix is not None else settings.s3_prefix
        ).strip().strip("/")
        if client is not None:
            self.client = client
        else:
            import boto3

            self.client = boto3.client(
                "s3",
                endpoint_url=settings.s3_endpoint_url.strip() or None,
                region_name=settings.s3_region.strip() or None,
                aws_access_key_id=settings.s3_access_key_id.get_secret_value() or None,
                aws_secret_access_key=settings.s3_secret_access_key.get_secret_value()
                or None,
                config=BotoConfig(
                    signature_version="s3v4",
                    s3={
                        "addressing_style": "path"
                        if settings.s3_use_path_style
                        else "auto"
                    },
                    retries={"max_attempts": 3, "mode": "standard"},
                ),
            )

    def _object_key(self, key: str) -> str:
        safe = key.strip().lstrip("/")
        return f"{self.prefix}/{safe}" if self.prefix else safe

    def save(self, content: bytes, suffix: str) -> str:
        key = f"{secrets.token_hex(16)}{suffix.lower()}"
        self.client.put_object(
            Bucket=self.bucket,
            Key=self._object_key(key),
            Body=content,
        )
        return key

    def read(self, key: str) -> bytes:
        try:
            response = self.client.get_object(
                Bucket=self.bucket, Key=self._object_key(key)
            )
        except ClientError as exc:
            if _is_not_found(exc):
                raise StorageObjectNotFound(key) from exc
            raise
        return response["Body"].read()

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=self._object_key(key))
        except ClientError as exc:
            if _is_not_found(exc):
                return False
            raise
        return True

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=self._object_key(key))
