-- Runs once when the database volume is first created.
-- The image's POSTGRES_USER owns the tables and runs migrations.
-- The API and worker connect as opscore_app: not a superuser and not the
-- table owner, so row-level security always applies to them.
CREATE ROLE opscore_app LOGIN PASSWORD 'change-me-app-password' NOSUPERUSER NOCREATEDB NOCREATEROLE;
GRANT CONNECT ON DATABASE opscore TO opscore_app;
GRANT USAGE ON SCHEMA public TO opscore_app;
ALTER DEFAULT PRIVILEGES FOR ROLE opscore IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO opscore_app;
