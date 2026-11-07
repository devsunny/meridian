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

from .utils import guess_media_type


class CloudDriveConnector(Connector):
    """Shared token + HTTP behaviour for OAuth SaaS content sources.

    The platform never performs the OAuth dance itself: an administrator stores a refresh/access
    token in the secret manager (or a token broker writes it), and the connector consumes the ref.
    """

    category = "saas"
    base_url = ""
    token_field = "token_ref"
    capabilities = ("test", "discover", "read")
    config_schema = [
        ConfigField("token_ref", "OAuth token secret", "secret", True, "", "env:GOOGLE_DRIVE_TOKEN"),
        ConfigField("folder_id", "Folder / drive id", "string", False, "", "Defaults to the account root."),
        ConfigField("max_files", "Max files", "integer", False, 200),
    ]

    def _token(self, secrets: dict[str, str | None]) -> str:
        token = secrets.get("token") or secrets.get("__connection__")
        if not token:
            raise ConnectorError("An OAuth access token is required.", code="missing_token")
        return token

    def _headers(self, ctx: ConnectorContext, secrets: dict[str, str | None]) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token(secrets)}", "X-Request-ID": ctx.request_id}

    def _client(self) -> httpx.Client:
        return httpx.Client(timeout=30.0, follow_redirects=True)

    def test(self, ctx: ConnectorContext, config: dict[str, Any], secrets: dict[str, str | None]) -> ConnectionTest:
        started = time.perf_counter()
        try:
            with self._client() as client:
                response = client.get(self._test_url(config), headers=self._headers(ctx, secrets))
            if response.status_code >= 400:
                return ConnectionTest(
                    False,
                    f"Provider returned HTTP {response.status_code}.",
                    int((time.perf_counter() - started) * 1000),
                )
            return ConnectionTest(
                True,
                "OAuth token accepted by the provider.",
                int((time.perf_counter() - started) * 1000),
            )
        except ConnectorError as exc:
            return ConnectionTest(False, str(exc), int((time.perf_counter() - started) * 1000))
        except httpx.HTTPError as exc:
            return ConnectionTest(False, f"Network error: {exc.__class__.__name__}")

    def discover(
        self, ctx: ConnectorContext, config: dict[str, Any], secrets: dict[str, str | None]
    ) -> Iterable[Resource]:
        with self._client() as client:
            response = client.get(
                self._list_url(config),
                headers=self._headers(ctx, secrets),
                params=self._list_params(config),
            )
        if response.status_code >= 400:
            raise ConnectorError(
                f"Provider returned HTTP {response.status_code}.",
                code="provider_error",
                retryable=response.status_code == 429,
            )
        return self._parse_listing(response.json(), config)

    def read(
        self,
        ctx: ConnectorContext,
        config: dict[str, Any],
        secrets: dict[str, str | None],
        resource: Resource,
        options: dict[str, Any] | None = None,
    ) -> Iterable[RecordBatch]:
        download_url = resource.metadata.get("download_url") or self._download_url(resource)
        with self._client() as client:
            response = client.get(download_url, headers=self._headers(ctx, secrets))
        if response.status_code >= 400:
            raise ConnectorError(
                f"Provider download returned HTTP {response.status_code}.",
                code="download_error",
                retryable=response.status_code == 429 or response.status_code >= 500,
            )
        yield RecordBatch(
            raw=RawAsset(
                filename=resource.name,
                content=response.content,
                media_type=resource.metadata.get("mime_type") or guess_media_type(resource.name),
                source_uri=resource.id,
                metadata={"size": len(response.content)},
            ),
            source_uri=resource.id,
        )

    # Provider hooks ---------------------------------------------------------------------------
    def _test_url(self, config: dict[str, Any]) -> str:
        raise NotImplementedError

    def _list_url(self, config: dict[str, Any]) -> str:
        raise NotImplementedError

    def _list_params(self, config: dict[str, Any]) -> dict[str, Any]:
        return {}

    def _parse_listing(self, payload: Any, config: dict[str, Any]) -> list[Resource]:
        raise NotImplementedError

    def _download_url(self, resource: Resource) -> str:
        raise NotImplementedError


@register
class GoogleDriveConnector(CloudDriveConnector):
    type = "gdrive"
    label = "Google Drive"
    description = "Google Drive folders and files using a Google OAuth access token."
    base_url = "https://www.googleapis.com/drive/v3"
    icon = "hard-drive"

    def _test_url(self, config: dict[str, Any]) -> str:
        return f"{self.base_url}/about?fields=user"

    def _list_url(self, config: dict[str, Any]) -> str:
        return f"{self.base_url}/files"

    def _list_params(self, config: dict[str, Any]) -> dict[str, Any]:
        folder = config.get("folder_id") or "root"
        return {
            "q": f"'{folder}' in parents and trashed=false",
            "fields": "files(id,name,mimeType,size,modifiedTime),nextPageToken",
            "pageSize": min(int(config.get("max_files", 200)), 1000),
        }

    def _parse_listing(self, payload: Any, config: dict[str, Any]) -> list[Resource]:
        return [
            Resource(
                id=item["id"],
                name=item["name"],
                kind="folder" if item.get("mimeType") == "application/vnd.google-apps.folder" else "file",
                size=int(item["size"]) if item.get("size") else None,
                modified_at=item.get("modifiedTime"),
                metadata={"mime_type": item.get("mimeType", "")},
            )
            for item in payload.get("files", [])
            if item.get("mimeType") != "application/vnd.google-apps.folder"
        ]

    def _download_url(self, resource: Resource) -> str:
        return f"{self.base_url}/files/{resource.id}?alt=media"


@register
class OneDriveConnector(CloudDriveConnector):
    type = "onedrive"
    label = "Microsoft OneDrive / SharePoint"
    description = "OneDrive or SharePoint document libraries through Microsoft Graph."
    base_url = "https://graph.microsoft.com/v1.0"
    icon = "cloud"

    def _test_url(self, config: dict[str, Any]) -> str:
        return f"{self.base_url}/me/drive"

    def _list_url(self, config: dict[str, Any]) -> str:
        folder = str(config.get("folder_id") or "").strip("/")
        if folder:
            return f"{self.base_url}/me/drive/items/{folder}/children"
        return f"{self.base_url}/me/drive/root/children"

    def _list_params(self, config: dict[str, Any]) -> dict[str, Any]:
        return {"$top": min(int(config.get("max_files", 200)), 999)}

    def _parse_listing(self, payload: Any, config: dict[str, Any]) -> list[Resource]:
        resources = []
        for item in payload.get("value", []):
            if "folder" in item:
                continue
            resources.append(
                Resource(
                    id=item["id"],
                    name=item["name"],
                    kind="file",
                    size=item.get("size"),
                    modified_at=item.get("lastModifiedDateTime"),
                    metadata={
                        "mime_type": (item.get("file") or {}).get("mimeType", ""),
                        "download_url": item.get("@microsoft.graph.downloadUrl", ""),
                        "web_url": item.get("webUrl", ""),
                    },
                )
            )
        return resources

    def _download_url(self, resource: Resource) -> str:
        if resource.metadata.get("download_url"):
            return str(resource.metadata["download_url"])
        return f"{self.base_url}/me/drive/items/{resource.id}/content"


@register
class BoxConnector(CloudDriveConnector):
    type = "box"
    label = "Box"
    description = "Box folders and files using a Box OAuth access token."
    base_url = "https://api.box.com/2.0"
    icon = "box"

    def _test_url(self, config: dict[str, Any]) -> str:
        return f"{self.base_url}/users/me"

    def _list_url(self, config: dict[str, Any]) -> str:
        folder = str(config.get("folder_id") or "0")
        return f"{self.base_url}/folders/{folder}/items"

    def _list_params(self, config: dict[str, Any]) -> dict[str, Any]:
        return {"limit": min(int(config.get("max_files", 200)), 1000), "fields": "id,name,type,size,modified_at"}

    def _parse_listing(self, payload: Any, config: dict[str, Any]) -> list[Resource]:
        resources = []
        for item in payload.get("entries", []):
            if item.get("type") != "file":
                continue
            resources.append(
                Resource(
                    id=item["id"],
                    name=item["name"],
                    kind="file",
                    size=item.get("size"),
                    modified_at=item.get("modified_at"),
                    metadata={"mime_type": guess_media_type(item["name"])},
                )
            )
        return resources

    def _download_url(self, resource: Resource) -> str:
        return f"{self.base_url}/files/{resource.id}/content"
