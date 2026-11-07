from __future__ import annotations

import time
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
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

from ..config import get_settings
from .utils import find_files, guess_media_type, match_name, resolve_path, utc_iso


@register
class FilesystemConnector(Connector):
    type = "file"
    label = "Files & uploads"
    category = "files"
    description = "Local files, shared volumes and user uploads: CSV, JSON, XML, Excel, PDF, Word and text."
    capabilities = ("test", "discover", "read")
    config_schema = [
        ConfigField("root", "Allowed root", "string", False, "", "Optional base directory. Paths are sandboxed."),
        ConfigField("path", "Path or glob", "string", True, "", "Relative path, directory or glob, e.g. data/*.csv"),
        ConfigField("recursive", "Recursive", "boolean", False, True),
        ConfigField("max_files", "Max files", "integer", False, 200),
    ]
    icon = "folder"

    def _roots(self, config: dict[str, Any]) -> list[Path]:
        if config.get("root"):
            return [Path(str(config["root"])).expanduser().resolve()]
        return get_settings().file_root_list

    def test(self, ctx: ConnectorContext, config: dict[str, Any], secrets: dict[str, str | None]) -> ConnectionTest:
        started = time.perf_counter()
        try:
            path = resolve_path(str(config.get("path", "")), config.get("root"), self._roots(config))
            if not path.exists():
                return ConnectionTest(False, f"Path does not exist: {path.name}")
            if path.is_file():
                size = path.stat().st_size
                return ConnectionTest(
                    True,
                    f"File is readable ({size:,} bytes).",
                    int((time.perf_counter() - started) * 1000),
                    {"kind": "file", "media_type": guess_media_type(path.name)},
                )
            count = len(find_files(path, str(config.get("pattern") or "*"), bool(config.get("recursive", True)), 5))
            return ConnectionTest(
                True,
                f"Directory is readable; {count} file(s) visible in sample.",
                int((time.perf_counter() - started) * 1000),
                {"kind": "directory", "path": path.name},
            )
        except ConnectorError as exc:
            return ConnectionTest(False, str(exc), int((time.perf_counter() - started) * 1000), {"code": exc.code})
        except OSError as exc:
            return ConnectionTest(False, f"Unable to read path: {exc.strerror or exc.__class__.__name__}")

    def discover(
        self, ctx: ConnectorContext, config: dict[str, Any], secrets: dict[str, str | None]
    ) -> Iterable[Resource]:
        path = resolve_path(str(config.get("path", "")), config.get("root"), self._roots(config))
        max_files = min(int(config.get("max_files", 200)), 2000)
        if path.is_file():
            files = [path]
        elif path.is_dir():
            files = find_files(
                path,
                str(config.get("pattern") or "*"),
                bool(config.get("recursive", True)),
                max_files,
            )
        else:
            # A glob was supplied.
            base = path.parent
            files = find_files(base, path.name, bool(config.get("recursive", False)), max_files)
        resources: list[Resource] = []
        for file_path in files:
            if not match_name(file_path.name, config.get("include")):
                continue
            stat = file_path.stat()
            resources.append(
                Resource(
                    id=str(file_path),
                    name=file_path.name,
                    kind="file",
                    path=str(file_path),
                    size=stat.st_size,
                    modified_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
                    metadata={"media_type": guess_media_type(file_path.name)},
                )
            )
        if not resources:
            raise ConnectorError("No files matched the configured path.", code="no_resources")
        return resources

    def read(
        self,
        ctx: ConnectorContext,
        config: dict[str, Any],
        secrets: dict[str, str | None],
        resource: Resource,
        options: dict[str, Any] | None = None,
    ) -> Iterable[RecordBatch]:
        path = Path(resource.path or resource.id).expanduser().resolve()
        roots = self._roots(config)
        if roots:
            from .utils import within

            if not within(path, roots):
                raise ConnectorError("Resolved file is outside allowed roots.", code="path_not_allowed")
        max_bytes = int((options or {}).get("max_bytes", 100 * 1024 * 1024))
        if path.stat().st_size > max_bytes:
            raise ConnectorError(
                f"File exceeds {max_bytes} bytes. Configure a larger max_bytes or split the source.",
                code="file_too_large",
            )
        ctx.logger.info(
            "connector_read_file",
            extra={"source_uri": str(path), "size": path.stat().st_size, "request_id": ctx.request_id},
        )
        yield RecordBatch(
            raw=RawAsset(
                filename=path.name,
                content=path.read_bytes(),
                media_type=guess_media_type(path.name),
                source_uri=str(path),
                metadata={"modified_at": utc_iso(), "size": path.stat().st_size},
            ),
            source_uri=str(path),
        )
