-- Migration: Add progress tracking fields to tasks table
-- This migration can be run on existing databases

-- Add progress columns if they don't exist
DO $$
BEGIN
    -- Add progress column
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'tasks' AND column_name = 'progress'
    ) THEN
        ALTER TABLE tasks ADD COLUMN progress INTEGER DEFAULT 0 CHECK (progress >= 0 AND progress <= 100);
    END IF;

    -- Add progress_message column
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'tasks' AND column_name = 'progress_message'
    ) THEN
        ALTER TABLE tasks ADD COLUMN progress_message TEXT;
    END IF;
END $$;

-- Update existing tasks to have progress = 0
UPDATE tasks SET progress = 0 WHERE progress IS NULL;

COMMENT ON COLUMN tasks.progress IS 'Task progress percentage (0-100)';
COMMENT ON COLUMN tasks.progress_message IS 'Human-readable progress message';
