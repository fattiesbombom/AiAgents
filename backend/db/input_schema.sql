-- Input DB schema (PostgreSQL + pgvector).

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS access_logs (
  id UUID PRIMARY KEY,
  badge_id VARCHAR,
  door_id VARCHAR,
  employee_id UUID,
  attempt_result VARCHAR,
  timestamp TIMESTAMPTZ,
  location VARCHAR
);

CREATE TABLE IF NOT EXISTS employees (
  id UUID PRIMARY KEY,
  name VARCHAR,
  department VARCHAR,
  role VARCHAR,
  badge_id VARCHAR UNIQUE,
  authorised_zones TEXT[]
);

CREATE TABLE IF NOT EXISTS motion_events (
  id UUID PRIMARY KEY,
  source_id VARCHAR,
  source_type VARCHAR,
  feed_source VARCHAR,
  detected_objects TEXT[],
  confidence FLOAT,
  snapshot_path VARCHAR,
  timestamp TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS alarm_events (
  id UUID PRIMARY KEY,
  alarm_type VARCHAR,
  zone VARCHAR,
  severity VARCHAR,
  timestamp TIMESTAMPTZ,
  acknowledged BOOLEAN DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS sop_documents (
  id UUID PRIMARY KEY,
  title VARCHAR,
  source_file VARCHAR,
  chunk_index INTEGER,
  content TEXT,
  embedding vector(768),
  created_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS sop_documents_embedding_hnsw_idx
  ON sop_documents
  USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS incident_agent_state (
  incident_id UUID PRIMARY KEY,
  state_json JSONB,
  updated_at TIMESTAMPTZ
);
