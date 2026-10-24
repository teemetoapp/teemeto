-- Initial database extensions for teemeto
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";

-- Grant basic permissions
GRANT ALL ON SCHEMA public TO teemeto_user;
