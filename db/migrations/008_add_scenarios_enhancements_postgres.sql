-- Migration 008: Scenario enhancements (PostgreSQL)
-- Date: 2026-02-26
-- Description: Adds status workflow fields, visibility, batch run support

-- TestCase enhancements
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'testcase' AND column_name = 'visibility'
    ) THEN
        ALTER TABLE testcase ADD COLUMN visibility VARCHAR DEFAULT 'public';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'testcase' AND column_name = 'approved_by'
    ) THEN
        ALTER TABLE testcase ADD COLUMN approved_by INTEGER;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'testcase' AND column_name = 'test_case_number'
    ) THEN
        ALTER TABLE testcase ADD COLUMN test_case_number INTEGER;
    END IF;
END $$;

-- TestRun batch/browser support
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'testrun' AND column_name = 'batch_label'
    ) THEN
        ALTER TABLE testrun ADD COLUMN batch_label VARCHAR;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'testrun' AND column_name = 'browser'
    ) THEN
        ALTER TABLE testrun ADD COLUMN browser VARCHAR;
    END IF;
END $$;

-- Project enhancements
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'project' AND column_name = 'base_prompt'
    ) THEN
        ALTER TABLE project ADD COLUMN base_prompt VARCHAR;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'project' AND column_name = 'page_load_state'
    ) THEN
        ALTER TABLE project ADD COLUMN page_load_state VARCHAR DEFAULT 'load';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'project' AND column_name = 'test_case_prefix'
    ) THEN
        ALTER TABLE project ADD COLUMN test_case_prefix VARCHAR;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'project' AND column_name = 'next_test_case_number'
    ) THEN
        ALTER TABLE project ADD COLUMN next_test_case_number INTEGER DEFAULT 1;
    END IF;
END $$;
