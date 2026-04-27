-- Bootstrap databases for app, Temporal and Langfuse.
-- Runs once on first postgres start.

CREATE DATABASE temporal;
CREATE DATABASE temporal_visibility;
CREATE DATABASE langfuse;

\connect app
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
