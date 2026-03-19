-- Output DB schema (PostgreSQL).

CREATE TABLE IF NOT EXISTS incidents (
  id UUID PRIMARY KEY,
  incident_type VARCHAR,
  priority VARCHAR,
  feed_source VARCHAR,
  source_type VARCHAR,
  location VARCHAR,
  confirmed BOOLEAN,
  risk_score FLOAT,
  recommended_action TEXT,
  incident_status VARCHAR,
  police_notified BOOLEAN,
  police_notification_type VARCHAR,
  human_review_status VARCHAR,
  created_at TIMESTAMPTZ,
  updated_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS incident_evidence (
  id UUID PRIMARY KEY,
  incident_id UUID REFERENCES incidents(id),
  evidence_type VARCHAR,
  file_path VARCHAR,
  description TEXT,
  created_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS incident_timeline (
  id UUID PRIMARY KEY,
  incident_id UUID REFERENCES incidents(id),
  node_name VARCHAR,
  summary TEXT,
  created_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS audit_log (
  id UUID PRIMARY KEY,
  incident_id UUID REFERENCES incidents(id),
  actor VARCHAR,
  action VARCHAR,
  detail JSONB,
  created_at TIMESTAMPTZ
);
