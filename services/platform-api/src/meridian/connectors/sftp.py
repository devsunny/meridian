from __future__ import annotations

import io
import stat
import time
from collections.abc import Iterable
from datetime import UTC, datetime
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
class SftpConnector(Connector):
    type = "sftp"
    label = "SFTP"
    category = "files"
    description = "SFTP file pickup with password or private-key auth and host-key verification."
    capabilities = ("test", "discover", "read")
    config_schema = [
        ConfigField("host", "Host", "string", True),
        ConfigField("port", "Port", "integer", False, 22),
        ConfigField("username", "Username", "string", True),
        ConfigField("path", "Remote path", "string", True, "", "/inbound/orders"),
        ConfigField("password_ref", "Password secret", "secret", False),
        ConfigField("private_key_ref", "Private key secret", "secret", False, "", "PEM content in env/secret manager"),
        ConfigField("strict_host_key", "Verify host key", "boolean", False, True),
        ConfigField("known_hosts", "Known hosts file", "string", False, "", "Required for strict mode"),
        ConfigField("max_files", "Max files", "integer", False, 200),
    ]
    icon = "server"

    def _connect(self, config: dict[str, Any], secrets: dict[str, str | None]):
        try:
            import paramiko
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise ConnectorError(
                "SFTP support is not installed. Install the platform 'sftp' extra (paramiko).",
                code="sftp_support_missing",
            ) from exc
        client = paramiko.SSHClient()
        known_hosts = config.get("known_hosts")
        if known_hosts:
            client.load_host_keys(str(known_hosts))
        strict = bool(config.get("strict_host_key", True))
        client.set_missing_host_key_policy(paramiko.RejectPolicy() if strict else paramiko.AutoAddPolicy())
        password = secret_for(config, secrets, "password")
        key_value = secret_for(config, secrets, "private_key")
        kwargs: dict[str, Any] = {
            "hostname": str(config["host"]),
            "port": int(config.get("port", 22)),
            "username": str(config["username"]),
            "timeout": 15,
            "banner_timeout": 15,
            "auth_timeout": 15,
        }
        if key_value:
            pkey = None
            for key_class in (paramiko.Ed25519Key, paramiko.ECDSAKey, paramiko.RSAKey):
                try:
                    pkey = key_class.from_private_key(io.StringIO(key_value))
                    break
                except Exception:  # noqa: BLE001
                    continue
            if pkey is None:
                raise ConnectorError("Unable to parse the configured private key.", code="invalid_private_key")
            kwargs["pkey"] = pkey
        elif password:
            kwargs["password"] = password
        else:
            raise ConnectorError("An SFTP password or private key is required.", code="missing_credentials")
        client.connect(**kwargs)
        return client

    def test(self, ctx: ConnectorContext, config: dict[str, Any], secrets: dict[str, str | None]) -> ConnectionTest:
        started = time.perf_counter()
        try:
            client = self._connect(config, secrets)
            sftp = client.open_sftp()
            sftp.stat(str(config.get("path") or "/"))
            sftp.close()
            client.close()
            return ConnectionTest(
                True,
                "SFTP authentication and path check succeeded.",
                int((time.perf_counter() - started) * 1000),
            )
        except ConnectorError as exc:
            return ConnectionTest(False, str(exc), int((time.perf_counter() - started) * 1000), {"code": exc.code})
        except Exception as exc:  # noqa: BLE001
            return ConnectionTest(False, f"SFTP failed: {exc.__class__.__name__}", int((time.perf_counter() - started) * 1000))

    def discover(
        self, ctx: ConnectorContext, config: dict[str, Any], secrets: dict[str, str | None]
    ) -> Iterable[Resource]:
        client = self._connect(config, secrets)
        try:
            sftp = client.open_sftp()
            path = str(config.get("path") or "/")
            attrs = sftp.listdir_attr(path)
            resources: list[Resource] = []
            for item in attrs[: min(int(config.get("max_files", 200)), 2000)]:
                if stat.S_ISDIR(item.st_mode or 0):
                    continue
                resources.append(
                    Resource(
                        id=f"{path.rstrip('/')}/{item.filename}",
                        name=item.filename,
                        kind="file",
                        path=f"{path.rstrip('/')}/{item.filename}",
                        size=item.st_size,
                        modified_at=datetime.fromtimestamp(item.st_mtime or 0, tz=UTC).isoformat(),
                        metadata={"media_type": guess_media_type(item.filename)},
                    )
                )
            return resources
        finally:
            client.close()

    def read(
        self,
        ctx: ConnectorContext,
        config: dict[str, Any],
        secrets: dict[str, str | None],
        resource: Resource,
        options: dict[str, Any] | None = None,
    ) -> Iterable[RecordBatch]:
        client = self._connect(config, secrets)
        try:
            sftp = client.open_sftp()
            path = resource.path or resource.id
            max_bytes = int((options or {}).get("max_bytes", 100 * 1024 * 1024))
            attrs = sftp.stat(path)
            if (attrs.st_size or 0) > max_bytes:
                raise ConnectorError("Remote file exceeds configured max_bytes.", code="file_too_large")
            with sftp.open(path, "rb") as handle:
                content = handle.read()
            filename = path.split("/")[-1]
            yield RecordBatch(
                raw=RawAsset(
                    filename=filename,
                    content=content,
                    media_type=guess_media_type(filename),
                    source_uri=f"sftp://{config['host']}{path}",
                ),
                source_uri=f"sftp://{config['host']}{path}",
            )
        finally:
            client.close()
