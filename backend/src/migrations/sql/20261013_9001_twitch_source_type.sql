ALTER TABLE sources DROP CONSTRAINT IF EXISTS sources_type_check;
ALTER TABLE sources DROP CONSTRAINT IF EXISTS check_source_type;
ALTER TABLE sources ADD CONSTRAINT sources_type_check CHECK (type IN ('youtube', 'video_url', 'twitch'))
