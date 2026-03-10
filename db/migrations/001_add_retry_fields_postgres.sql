-- Migration: Add retry tracking fields to testrun table (PostgreSQL)
-- Date: 2026-01-31
-- Description: Adds columns for test-level retry support

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'testrun' AND column_name = 'retry_attempt'
    ) THEN
        ALTER TABLE testrun ADD COLUMN retry_attempt INTEGER DEFAULT 0;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'testrun' AND column_name = 'max_retries'
    ) THEN
        ALTER TABLE testrun ADD COLUMN max_retries INTEGER DEFAULT 0;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'testrun' AND column_name = 'original_run_id'
    ) THEN
        ALTER TABLE testrun ADD COLUMN original_run_id INTEGER REFERENCES testrun(id) ON DELETE SET NULL;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'testrun' AND column_name = 'retry_mode'
    ) THEN
        ALTER TABLE testrun ADD COLUMN retry_mode VARCHAR;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'testrun' AND column_name = 'retry_reason'
    ) THEN
        ALTER TABLE testrun ADD COLUMN retry_reason VARCHAR;
    END IF;
END $$;

-- Add index for efficient retry group lookups
CREATE INDEX IF NOT EXISTS ix_testrun_original_run_id ON testrun(original_run_id);
