-- Migration 006: Add environments feature (PostgreSQL)
-- Date: 2026-02-26
-- Description: Creates environment table for per-project env config

CREATE TABLE IF NOT EXISTS environment (
    id SERIAL PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    name VARCHAR NOT NULL,
    base_url VARCHAR NOT NULL,
    variables VARCHAR NOT NULL DEFAULT '{}',
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_environment_project_id ON environment(project_id);
CREATE INDEX IF NOT EXISTS ix_environment_name ON environment(name);
