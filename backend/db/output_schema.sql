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
  human_reviewer_rank VARCHAR,
  responder_rank VARCHAR,
  responder_role_label VARCHAR,
  responder_permissions JSONB,
  can_approve_escalation BOOLEAN,
  can_operate_scc BOOLEAN,
  assigned_zone VARCHAR,
  deployment_type VARCHAR,
  dispatch_instruction TEXT,
  dispatched_officer_role VARCHAR,
  dispatch_sent_at TIMESTAMPTZ,
  incident_report_generated BOOLEAN DEFAULT FALSE,
  incident_report_path VARCHAR,
  created_at TIMESTAMPTZ,
  updated_at TIMESTAMPTZ
);

-- Existing deployments: add Certis rank / review columns (idempotent).
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS human_reviewer_rank VARCHAR;
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS responder_rank VARCHAR;
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS responder_role_label VARCHAR;
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS responder_permissions JSONB;
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS can_approve_escalation BOOLEAN;
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS can_operate_scc BOOLEAN;
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS assigned_zone VARCHAR;
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS deployment_type VARCHAR;
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS dispatch_instruction TEXT;
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS dispatched_officer_role VARCHAR;
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS dispatch_sent_at TIMESTAMPTZ;
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS incident_report_generated BOOLEAN;
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS incident_report_path VARCHAR;

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

CREATE TABLE IF NOT EXISTS shift_reports (
  id UUID PRIMARY KEY,
  summary TEXT NOT NULL,
  routine_incident_id UUID REFERENCES incidents(id),
  scheduled_task_id VARCHAR,
  created_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS dispatch_notifications (
  id UUID PRIMARY KEY,
  incident_id UUID REFERENCES incidents(id),
  instruction TEXT,
  dispatched_officer_role VARCHAR,
  dispatched_by VARCHAR,
  sent_at TIMESTAMPTZ,
  acknowledged BOOLEAN DEFAULT FALSE,
  acknowledged_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS incident_reports (
  id UUID PRIMARY KEY,
  incident_id UUID REFERENCES incidents(id),
  report_text TEXT,
  report_type VARCHAR,
  generated_by VARCHAR,
  generated_at TIMESTAMPTZ,
  submitted BOOLEAN DEFAULT FALSE,
  submitted_at TIMESTAMPTZ
);

-- Daily routine / work-schedule row per officer (optional; empty = dashboard empty state).
CREATE TABLE IF NOT EXISTS officer_daily_tasks (
  id UUID PRIMARY KEY,
  task_date DATE NOT NULL,
  officer_rank VARCHAR NOT NULL,
  zone VARCHAR,
  task_type VARCHAR,
  status VARCHAR,
  description TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS officer_daily_tasks_lookup_idx
  ON officer_daily_tasks (task_date, officer_rank, zone);
