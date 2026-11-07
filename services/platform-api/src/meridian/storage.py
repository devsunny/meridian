from __future__ import annotations

import io
import json
import os
import tempfile
from abc import ABC, abstractmethod
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .config import get_settings


class Storage(ABC):
    @abstractmethod
    def put_bytes(self, key: str, data: bytes, content_type: str | None = None) -> str: ...

    @abstractmethod
    def get_bytes(self, key: str) -> bytes: ...

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def size(self, key: str) -> int: ...

    def put_jsonl(self, key: str, records: Iterator[dict[str, Any]] | list[dict[str, Any]]) -> int:
        buffer = io.StringIO()
        count = 0
        for record in records:
            buffer.write(json.dumps(record, ensure_ascii=False, default=str, separators=(",", ":")))
            buffer.write("\n")
            count += 1
        self.put_bytes(key, buffer.getvalue().encode("utf-8"), "application/x-ndjson")
        return count

    def read_jsonl(self, key: str, limit: int | None = None, offset: int = 0) -> list[dict[str, Any]]:
        content = self.get_bytes(key).decode("utf-8", errors="replace")
        records: list[dict[str, Any]] = []
        for index, line in enumerate(content.splitlines()):
            if index < offset:
                continue
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
            if limit is not None and len(records) >= limit:
                break
        return records

    def iter_jsonl(self, key: str) -> Iterator[dict[str, Any]]:
        content = self.get_bytes(key).decode("utf-8", errors="replace")
        for line in content.splitlines():
            if line.strip():
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue

    def local_path(self, key: str) -> Path | None:
        return None


class LocalStorage(Storage):
    def __init__(self, root: str) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = (self.root / key.lstrip("/\\")).resolve()
        if not str(path).startswith(str(self.root)):
            raise ValueError("storage key escapes root")
        return path

    def put_bytes(self, key: str, data: bytes, content_type: str | None = None) -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        return key

    def get_bytes(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def size(self, key: str) -> int:
        path = self._path(key)
        return path.stat().st_size if path.is_file() else 0

    def local_path(self, key: str) -> Path | None:
        return self._path(key)


class S3Storage(Storage):
    def __init__(self) -> None:
        import boto3

        settings = get_settings()
        self.bucket = settings.s3_bucket
        self.prefix = settings.s3_prefix.strip("/")
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            region_name=settings.s3_region,
        )

    def _key(self, key: str) -> str:
        return f"{self.prefix}/{key.lstrip('/')}" if self.prefix else key.lstrip("/")

    def put_bytes(self, key: str, data: bytes, content_type: str | None = None) -> str:
        self.client.put_object(
            Bucket=self.bucket,
            Key=self._key(key),
            Body=data,
            ContentType=content_type or "application/octet-stream",
        )
        return key

    def get_bytes(self, key: str) -> bytes:
        response = self.client.get_object(Bucket=self.bucket, Key=self._key(key))
        return response["Body"].read()

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self.client.head_object(Bucket=self.bucket, Key=self._key(key))
            return True
        except ClientError:
            return False

    def size(self, key: str) -> int:
        try:
            return int(self.client.head_object(Bucket=self.bucket, Key=self._key(key))["ContentLength"])
        except Exception:  # noqa: BLE001
            return 0


_storage: Storage | None = None


def get_storage() -> Storage:
    global _storage
    if _storage is None:
        settings = get_settings()
        _storage = S3Storage() if settings.storage_backend == "s3" else LocalStorage(settings.storage_root)
    return _storage


def reset_storage() -> None:
    global _storage
    _storage = None


def dataset_key(tenant_id: str, dataset_id: str, version: int) -> str:
    return f"{tenant_id}/datasets/{dataset_id}/v{version:04d}/data.jsonl"


def upload_key(tenant_id: str, upload_id: str, filename: str) -> str:
    safe = "".join(ch for ch in filename if ch.isalnum() or ch in "._- ").strip().replace(" ", "_")
    return f"{tenant_id}/uploads/{upload_id}/{safe or 'file'}"
