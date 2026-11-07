from __future__ import annotations

import time
from collections.abc import Iterable
from typing import Any

from edp_connector_sdk import (
    ConfigField,
    ConnectionTest,
    Connector,
    ConnectorContext,
    ConnectorError,
    RawAsset,
    RecordBatch,
    Resource,
    register,
)

from ..secrets import secret_for
from .utils import guess_media_type


@register
class S3Connector(Connector):
    type = "s3"
    label = "Amazon S3"
    category = "object-store"
    description = "S3 and S3-compatible object storage with prefix discovery and bounded object reads."
    capabilities = ("test", "discover", "read")
    config_schema = [
        ConfigField("bucket", "Bucket", "string", True),
        ConfigField("prefix", "Prefix", "string", False, ""),
        ConfigField("region", "Region", "string", False, "us-east-1"),
        ConfigField("endpoint_url", "Endpoint URL", "string", False, "", "For MinIO/SeaweedFS; leave blank on AWS."),
        ConfigField("access_key_ref", "Access key secret", "secret", False, "", "Prefer IRSA on EKS."),
        ConfigField("secret_key_ref", "Secret key secret", "secret", False, ""),
        ConfigField("max_objects", "Max objects", "integer", False, 500),
    ]
    icon = "cloud"

    def _client(self, config: dict[str, Any], secrets: dict[str, str | None]):
        import boto3

        access_key = secret_for(config, secrets, "access_key")
        secret_key = secret_for(config, secrets, "secret_key")
        kwargs: dict[str, Any] = {"region_name": config.get("region") or "us-east-1"}
        if config.get("endpoint_url"):
            kwargs["endpoint_url"] = config["endpoint_url"]
        if access_key and secret_key:
            kwargs["aws_access_key_id"] = access_key
            kwargs["aws_secret_access_key"] = secret_key
        return boto3.client("s3", **kwargs)

    def test(self, ctx: ConnectorContext, config: dict[str, Any], secrets: dict[str, str | None]) -> ConnectionTest:
        started = time.perf_counter()
        try:
            client = self._client(config, secrets)
            client.head_bucket(Bucket=str(config["bucket"]))
            return ConnectionTest(
                True,
                "Bucket is reachable.",
                int((time.perf_counter() - started) * 1000),
                {"bucket": config["bucket"]},
            )
        except Exception as exc:  # noqa: BLE001
            return ConnectionTest(False, f"S3 check failed: {exc.__class__.__name__}", int((time.perf_counter() - started) * 1000))

    def discover(
        self, ctx: ConnectorContext, config: dict[str, Any], secrets: dict[str, str | None]
    ) -> Iterable[Resource]:
        client = self._client(config, secrets)
        bucket = str(config["bucket"])
        prefix = str(config.get("prefix") or "")
        max_objects = min(int(config.get("max_objects", 500)), 5000)
        resources: list[Resource] = []
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                resources.append(
                    Resource(
                        id=obj["Key"],
                        name=obj["Key"].split("/")[-1],
                        kind="object",
                        path=obj["Key"],
                        size=obj.get("Size"),
                        modified_at=obj["LastModified"].isoformat() if obj.get("LastModified") else None,
                        metadata={"bucket": bucket, "etag": obj.get("ETag", "").strip('"')},
                    )
                )
                if len(resources) >= max_objects:
                    return resources
        return resources

    def read(
        self,
        ctx: ConnectorContext,
        config: dict[str, Any],
        secrets: dict[str, str | None],
        resource: Resource,
        options: dict[str, Any] | None = None,
    ) -> Iterable[RecordBatch]:
        client = self._client(config, secrets)
        bucket = str(config["bucket"])
        key = resource.path or resource.id
        max_bytes = int((options or {}).get("max_bytes", 100 * 1024 * 1024))
        head = client.head_object(Bucket=bucket, Key=key)
        if int(head.get("ContentLength", 0)) > max_bytes:
            raise ConnectorError("Object exceeds configured max_bytes.", code="object_too_large")
        response = client.get_object(Bucket=bucket, Key=key)
        content = response["Body"].read()
        filename = key.split("/")[-1]
        yield RecordBatch(
            raw=RawAsset(
                filename=filename,
                content=content,
                media_type=response.get("ContentType") or guess_media_type(filename),
                source_uri=f"s3://{bucket}/{key}",
                metadata={"etag": head.get("ETag", "").strip('"'), "size": len(content)},
            ),
            source_uri=f"s3://{bucket}/{key}",
        )
