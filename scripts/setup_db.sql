-- GovFleet local database bootstrap. Run as a PostgreSQL superuser via
-- scripts/setup_db.ps1, which passes :app_user, :app_password, :db_name.
--
-- Security model:
--   * The app connects as a dedicated least-privilege role (no SUPERUSER,
--     no CREATEROLE). CREATEDB is granted only so the Django test runner
--     can create/destroy its throwaway test database; drop it in production.
--   * The role owns only its own database, so it can create the trusted
--     `btree_gist` extension needed by the overlap exclusion constraint.
--   * PUBLIC cannot connect to the database.

\set ON_ERROR_STOP on

SELECT format(
    'CREATE ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOCREATEROLE CREATEDB NOREPLICATION',
    :'app_user', :'app_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'app_user') \gexec

-- Keep the password in sync with .env if the role already existed.
SELECT format('ALTER ROLE %I WITH PASSWORD %L', :'app_user', :'app_password') \gexec

SELECT format(
    'CREATE DATABASE %I OWNER %I ENCODING ''UTF8'' TEMPLATE template0',
    :'db_name', :'app_user')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'db_name') \gexec

REVOKE ALL ON DATABASE :"db_name" FROM PUBLIC;
GRANT CONNECT, TEMPORARY ON DATABASE :"db_name" TO :"app_user";

\echo 'GovFleet database and role are ready.'
