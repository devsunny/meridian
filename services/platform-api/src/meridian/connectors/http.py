from __future__ import annotations

import time
from collections.abc import Iterable
from typing import Any

import httpx
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

from .utils import extract_json_path, guess_media_type, json_safe, records_from_payload


@register
class HttpConnector(Connector):
    type = "rest"
    label = "REST / JSON API"
    category = "api"
    description = "HTTP APIs with bearer/header auth, JSON record extraction and simple cursor pagination."
    capabilities = ("test", "discover", "read")
    config_schema = [
        ConfigField("url", "Endpoint URL", "string", True, "", "https://api.example.com/v1/orders"),
        ConfigField("method", "Method", "select", False, "GET", options=("GET", "POST")),
        ConfigField("records_path", "Records path", "string", False, "", "Dot path to the array, e.g. data.items"),
        ConfigField("auth_header", "Auth header", "string", False, "Authorization"),
        ConfigField("auth_scheme", "Auth scheme", "string", False, "Bearer"),
        ConfigField("headers", "Extra headers (JSON)", "textarea", False, "{}"),
        ConfigField("body", "POST body (JSON)", "textarea", False, "{}"),
        ConfigField("next_url_path", "Next URL path", "string", False, "", "Dot path to next page URL"),
        ConfigField("max_pages", "Max pages", "integer", False, 5),
        ConfigField("verify_tls", "Verify TLS", "boolean", False, True),
    ]
    icon = "globe"

    def _client(self, config: dict[str, Any]) -> httpx.Client:
        return httpx.Client(
            timeout=httpx.Timeout(30.0, connect=10.0),
            follow_redirects=True,
            verify=bool(config.get("verify_tls", True)),
        )

    def _request(
        self,
        ctx: ConnectorContext,
        config: dict[str, Any],
        secrets: dict[str, str | None],
        url: str | None = None,
    ) -> httpx.Response:
        headers = {"Accept": "application/json, text/csv, application/xml;q=0.9, */*;q=0.8"}
        headers.update(config.get("headers") or {})
        token = secrets.get("token") or secrets.get("__connection__")
        if token:
            header = str(config.get("auth_header") or "Authorization")
            scheme = str(config.get("auth_scheme") or "Bearer").strip()
            headers[header] = f"{scheme} {token}".strip()
        headers["X-Request-ID"] = ctx.request_id
        method = str(config.get("method") or "GET").upper()
        body = config.get("body") or None
        with self._client(config) as client:
            response = client.request(method, url or str(config["url"]), headers=headers, json=body if method == "POST" else None)
            if response.status_code >= 400:
                raise ConnectorError(
                    f"Source returned HTTP {response.status_code}.",
                    code="http_error",
                    retryable=response.status_code in {408, 429} or response.status_code >= 500,
                    details={"status": response.status_code, "url": response.request.url.host},
                )
            return response

    def test(self, ctx: ConnectorContext, config: dict[str, Any], secrets: dict[str, str | None]) -> ConnectionTest:
        started = time.perf_counter()
        try:
            response = self._request(ctx, config, secrets)
            return ConnectionTest(
                True,
                f"Endpoint returned HTTP {response.status_code}.",
                int((time.perf_counter() - started) * 1000),
                {"status": response.status_code, "content_type": response.headers.get("content-type", "")},
            )
        except ConnectorError as exc:
            return ConnectionTest(False, str(exc), int((time.perf_counter() - started) * 1000), {"code": exc.code})
        except httpx.HTTPError as exc:
            return ConnectionTest(False, f"Network error: {exc.__class__.__name__}")

    def discover(
        self, ctx: ConnectorContext, config: dict[str, Any], secrets: dict[str, str | None]
    ) -> Iterable[Resource]:
        response = self._request(ctx, config, secrets)
        content_type = response.headers.get("content-type", "")
        records: list[dict[str, Any]] = []
        if "json" in content_type:
            try:
                payload = response.json()
                records = records_from_payload(payload, config.get("records_path"))
            except ValueError:
                pass
        return [
            Resource(
                id=str(config["url"]),
                name=str(config.get("name") or config["url"]).rstrip("/").split("/")[-1] or "endpoint",
                kind="api",
                path=str(config["url"]),
                metadata={
                    "status": response.status_code,
                    "content_type": content_type,
                    "sample_count": len(records),
                    "sample_keys": sorted(records[0].keys())[:40] if records else [],
                },
            )
        ]

    def read(
        self,
        ctx: ConnectorContext,
        config: dict[str, Any],
        secrets: dict[str, str | None],
        resource: Resource,
        options: dict[str, Any] | None = None,
    ) -> Iterable[RecordBatch]:
        url: str | None = str(config["url"])
        max_pages = min(int(config.get("max_pages", 5)), 100)
        for _page in range(max_pages):
            if not url:
                break
            response = self._request(ctx, config, secrets, url=url)
            content_type = response.headers.get("content-type", "")
            if "json" in content_type:
                try:
                    payload = response.json()
                except ValueError as exc:
                    raise ConnectorError("Source returned invalid JSON.", code="invalid_json") from exc
                records = [json_safe(record) for record in records_from_payload(payload, config.get("records_path"))]
                yield RecordBatch(records=records, source_uri=resource.id)
                next_path = config.get("next_url_path")
                next_value = extract_json_path(payload, next_path) if next_path else None
                if not next_value:
                    break
                url = str(next_value)
            else:
                filename = resource.name or "response"
                if "html" in content_type:
                    filename = f"{filename}.html"
                elif "xml" in content_type:
                    filename = f"{filename}.xml"
                elif "csv" in content_type:
                    filename = f"{filename}.csv"
                yield RecordBatch(
                    raw=RawAsset(
                        filename=filename,
                        content=response.content,
                        media_type=content_type.split(";")[0] or guess_media_type(filename),
                        source_uri=resource.id,
                    ),
                    source_uri=resource.id,
                )
                break
