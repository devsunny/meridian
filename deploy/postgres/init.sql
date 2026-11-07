-- Local development bootstrap.
-- Auto-setup creates schemas, but the databases must exist first.
CREATE DATABASE temporal;
CREATE DATABASE lakekeeper;
CREATE DATABASE keycloak;

\connect edp

CREATE SCHEMA IF NOT EXISTS iam;
CREATE SCHEMA IF NOT EXISTS connect;
CREATE SCHEMA IF NOT EXISTS ingest;
CREATE SCHEMA IF NOT EXISTS orchestrate;
CREATE SCHEMA IF NOT EXISTS catalog;
CREATE SCHEMA IF NOT EXISTS govern;
CREATE SCHEMA IF NOT EXISTS configure;
CREATE SCHEMA IF NOT EXISTS audit;
CREATE SCHEMA IF NOT EXISTS assist;
CREATE SCHEMA IF NOT EXISTS usage;

-- Local-only role used by services in development. In AWS this is an IAM-authenticated role.
CREATE ROLE edp_app LOGIN PASSWORD 'edp_app';
GRANT USAGE ON SCHEMA iam, connect, ingest, orchestrate, catalog, govern, configure, audit, assist, usage TO edp_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA iam, connect, ingest, orchestrate, catalog, govern, configure, audit, assist, usage
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO edp_app;

-- The audit table is append-only: no UPDATE/DELETE grant in production (enforced by a separate role).
COMMENT ON SCHEMA audit IS 'Append-only. Production role has INSERT and SELECT only.';
