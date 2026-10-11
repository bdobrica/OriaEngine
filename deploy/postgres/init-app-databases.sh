#!/bin/sh
# Fresh-volume bootstrap only. Schema migrations belong to each application's image.
set -eu
psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set ON_ERROR_STOP=1 <<'SQL'
\getenv oria_password ORIA_POSTGRES_PASSWORD
\getenv context_password SECOND_CONTEXT_POSTGRES_PASSWORD
SELECT format('CREATE ROLE oria LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD %L', :'oria_password') \gexec
SELECT format('CREATE ROLE secondcontext LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD %L', :'context_password') \gexec
CREATE DATABASE oria OWNER oria;
CREATE DATABASE secondcontext OWNER secondcontext;
REVOKE ALL ON DATABASE oria FROM PUBLIC;
REVOKE ALL ON DATABASE secondcontext FROM PUBLIC;
SQL
