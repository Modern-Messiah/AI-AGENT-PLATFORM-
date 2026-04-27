"""Thin MinIO wrapper. Lazy: connects on first use, not on import."""

from __future__ import annotations

from functools import cached_property
from io import BytesIO

from minio import Minio

from packages.core import settings


class ObjectStore:
    @cached_property
    def _client(self) -> Minio:
        client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=False,
        )
        if not client.bucket_exists(settings.minio_bucket):
            client.make_bucket(settings.minio_bucket)
        return client

    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        self._client.put_object(
            settings.minio_bucket,
            key,
            BytesIO(data),
            length=len(data),
            content_type=content_type,
        )
        return key

    def get(self, key: str) -> bytes:
        resp = self._client.get_object(settings.minio_bucket, key)
        try:
            return resp.read()
        finally:
            resp.close()
            resp.release_conn()


object_store = ObjectStore()
