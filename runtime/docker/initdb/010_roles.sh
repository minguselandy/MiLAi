#!/usr/bin/env bash
set -Eeuo pipefail

: "${POSTGRES_USER:?POSTGRES_USER is required}"
: "${POSTGRES_DB:?POSTGRES_DB is required}"
: "${MILAI_API_DB_PASSWORD:?MILAI_API_DB_PASSWORD is required}"
: "${MILAI_STEWARD_DB_PASSWORD:?MILAI_STEWARD_DB_PASSWORD is required}"
: "${MILAI_WORKER_DB_PASSWORD:?MILAI_WORKER_DB_PASSWORD is required}"
: "${MILAI_AUDIT_DB_PASSWORD:?MILAI_AUDIT_DB_PASSWORD is required}"

psql --set=ON_ERROR_STOP=1 \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  --set=api_password="$MILAI_API_DB_PASSWORD" \
  --set=steward_password="$MILAI_STEWARD_DB_PASSWORD" \
  --set=worker_password="$MILAI_WORKER_DB_PASSWORD" \
  --set=audit_password="$MILAI_AUDIT_DB_PASSWORD" <<'SQL'
SELECT format(
  'CREATE ROLE milai_api LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS',
  :'api_password'
) WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'milai_api') \gexec

SELECT format(
  'CREATE ROLE milai_steward LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS',
  :'steward_password'
) WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'milai_steward') \gexec

SELECT format(
  'CREATE ROLE milai_worker LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS',
  :'worker_password'
) WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'milai_worker') \gexec

SELECT format(
  'CREATE ROLE milai_audit LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS',
  :'audit_password'
) WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'milai_audit') \gexec

SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', current_database()) \gexec
SELECT format(
  'GRANT CONNECT ON DATABASE %I TO milai_api, milai_steward, milai_worker, milai_audit',
  current_database()
) \gexec
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
SQL
