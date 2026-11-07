# Meridian Connector SDK

The SDK is the stable contract between the Meridian control plane and connector implementations.
It has **no dependency on the platform** and contains no network, database, or cloud SDK code.

```python
from edp_connector_sdk import ConfigField, Connector, ConnectorContext, RawAsset, RecordBatch, Resource, register

@register
class MyConnector(Connector):
    type = "my-system"
    label = "My System"
    capabilities = ("discover", "read")
    config_schema = [ConfigField("url", "Base URL", required=True)]

    def test(self, ctx, config, secrets):
        return {"ok": True, "message": "reachable"}

    def discover(self, ctx, config, secrets):
        return [Resource(id="items", name="items", kind="table")]

    def read(self, ctx, config, secrets, resource, options):
        yield RecordBatch(records=[{"id": 1}], source_uri=resource.id)

register(MyConnector)
```

Discovery is via the `meridian.connectors` Python entry-point group:

```toml
[project.entry-points."meridian.connectors"]
my_system = "my_package.connector:MyConnector"
```

## Rules

- Never return credentials, tokens, or secret values in logs, resources, or records.
- Use `ctx.resolve_secret(secret_ref)`; never read secret environment variables directly.
- Honor `ctx.request_id` on every outbound request (`X-Request-ID`).
- Emit bounded batches. An ingestion must be restartable from its cursor.
- Declare `capabilities` honestly. The control plane hides unsupported actions.
- Package the connector as a container and pin dependency licenses (Apache-2.0, MIT, BSD preferred).
