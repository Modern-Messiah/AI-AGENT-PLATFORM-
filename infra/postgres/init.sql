-- Bootstrap databases for app and Temporal.
-- Runs once on first postgres start.

CREATE DATABASE temporal;
CREATE DATABASE temporal_visibility;


\connect app
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
