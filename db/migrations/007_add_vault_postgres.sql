-- Migration 007: Add vault feature (credential types + test data) (PostgreSQL)
-- Date: 2026-02-26
-- Description: Extends persona with credential types, adds testdata table

-- Extend persona table with multi-credential fields
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'persona' AND column_name = 'credential_type'
    ) THEN
        ALTER TABLE persona ADD COLUMN credential_type VARCHAR NOT NULL DEFAULT 'login';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'persona' AND column_name = 'environment_id'
    ) THEN
        ALTER TABLE persona ADD COLUMN environment_id INTEGER REFERENCES environment(id) ON DELETE SET NULL;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'persona' AND column_name = 'encrypted_api_key'
    ) THEN
        ALTER TABLE persona ADD COLUMN encrypted_api_key VARCHAR;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'persona' AND column_name = 'encrypted_token'
    ) THEN
        ALTER TABLE persona ADD COLUMN encrypted_token VARCHAR;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'persona' AND column_name = 'encrypted_metadata'
    ) THEN
        ALTER TABLE persona ADD COLUMN encrypted_metadata VARCHAR;
    END IF;
END $$;

-- TestData table
CREATE TABLE IF NOT EXISTS testdata (
    id SERIAL PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    environment_id INTEGER REFERENCES environment(id) ON DELETE SET NULL,
    name VARCHAR NOT NULL,
    description VARCHAR,
    data VARCHAR NOT NULL,
    tags VARCHAR,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_testdata_project_id ON testdata(project_id);
CREATE INDEX IF NOT EXISTS ix_testdata_name ON testdata(name);
