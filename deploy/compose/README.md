# Local Application Stack

`app.yaml` runs the reference product end to end:

| Service | Image / build | Port |
|---|---|---|
| `web` | `apps/web/Dockerfile` | 3000 |
| `api` | `services/platform-api/Dockerfile` | 8000 |
| `worker` | same API image, `python -m meridian.engine.worker` | — |
| `scheduler` | same API image, `python -m meridian.engine.scheduler` | — |
| `postgres` | `postgres:16-alpine` | 5432 |

Optional profiles:

- `--profile obs`: OpenTelemetry Collector, Prometheus, Jaeger. Set `MERIDIAN_OTEL_ENABLED=true`.
- `--profile objectstore`: SeaweedFS S3-compatible store on port 8333. Set `MERIDIAN_STORAGE_BACKEND=s3`,
  `MERIDIAN_S3_ENDPOINT_URL=http://seaweedfs:8333`, `MERIDIAN_S3_BUCKET=meridian`. Create the bucket with
  `weed shell` (or point the app at AWS S3 instead).

## Start

```bash
cp .env.example .env
# edit MERIDIAN_JWT_SECRET, then:
docker compose -f app.yaml up --build -d
docker compose -f app.yaml ps
```

Open http://localhost:3000 and sign in as `admin@meridian.local` / `Meridian123!`.

## Observe

```bash
docker compose -f app.yaml logs -f api
docker compose -f app.yaml logs -f worker
docker compose -f app.yaml --profile obs up -d
# Prometheus  http://localhost:9090
# Jaeger      http://localhost:16686
```

The API writes JSONL to the shared `appdata` volume and to stdout. Per-run logs are available from the UI
and `GET /api/v1/runs/{id}/logs`.

## Reset

```bash
docker compose -f app.yaml down
docker compose -f app.yaml down -v   # deletes Postgres data and the lake volume
```

## Production notes

- Replace local JWT auth with OIDC (`MERIDIAN_AUTH_MODE=oidc`) and disable demo seeding.
- Set a 32+ byte random `MERIDIAN_JWT_SECRET`.
- Put Postgres on RDS and the lake on S3 with KMS/versioning.
- Use the EKS guide in `../eks/README.md`; do not deploy this Compose file as production.
