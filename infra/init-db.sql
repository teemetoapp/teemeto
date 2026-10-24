-- Initial database extensions for teemeto
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";

-- Grant basic permissions to owner
GRANT ALL ON SCHEMA public TO teemeto_user;

-- Application role with NOBYPASSRLS and NOSUPERUSER for strict RLS enforcement
DO $do$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'teemeto_app') THEN
        CREATE ROLE teemeto_app WITH LOGIN PASSWORD 'teemeto_app_pass' NOSUPERUSER NOBYPASSRLS;
    END IF;
END
$do$;

GRANT ALL ON SCHEMA public TO teemeto_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO teemeto_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO teemeto_app;

