-- Migration 005: Add folders feature (PostgreSQL)
-- Date: 2026-02-26
-- Description: Creates testfolder table and adds folder_id to testcase

-- TestFolder table
CREATE TABLE IF NOT EXISTS testfolder (
    id SERIAL PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    parent_id INTEGER REFERENCES testfolder(id) ON DELETE SET NULL,
    name VARCHAR NOT NULL,
    description VARCHAR,
    folder_type VARCHAR NOT NULL DEFAULT 'regular',
    smart_criteria VARCHAR,
    order_index INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_testfolder_name ON testfolder(name);
CREATE INDEX IF NOT EXISTS ix_testfolder_project_id ON testfolder(project_id);

-- Add folder_id to testcase
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'testcase' AND column_name = 'folder_id'
    ) THEN
        ALTER TABLE testcase ADD COLUMN folder_id INTEGER REFERENCES testfolder(id) ON DELETE SET NULL;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_testcase_folder_id ON testcase(folder_id);
