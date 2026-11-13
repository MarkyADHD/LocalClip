-- AI-suggested hashtags for posting a clip (space-separated, no # sign).
ALTER TABLE generated_clips ADD COLUMN IF NOT EXISTS hashtags VARCHAR(300);
