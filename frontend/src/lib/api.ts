export type HumanReviewStatus = "pending" | "approved" | "rejected" | null;

export type CertisRank = "SO" | "SSO" | "SS" | "SSS" | "CSO";

export type IncidentSourceType =
  | "body_worn"
  | "cctv"
  | "fire_alarm"
  | "intruder_alarm"
  | "lift_alarm"
  | "door_alarm"
  | "mop_report"
  | "c2_system"
  | "nursing_intercom"
  | "carpark_intercom"
  | "manual_trigger"
  | "watch_heartbeat";

export type Incident = {
  id: string;
  incident_type?: string;
  priority?: string;
  feed_source?: "live" | "remote";
  source_type?: IncidentSourceType;
  location?: string;
  confirmed?: boolean;
  risk_score?: number;
  recommended_action?: string;
  incident_status?: string;
  police_notified?: boolean;
  police_notification_type?: string | null;
  human_review_status?: HumanReviewStatus;
  human_reviewer_rank?: CertisRank | null;
  responder_rank?: CertisRank | null;
  responder_role_label?: string | null;
  responder_permissions?: string[] | null;
  can_approve_escalation?: boolean;
  can_operate_scc?: boolean;
  assigned_zone?: string | null;
  deployment_type?: "ground" | "command_centre" | null;
  created_at?: string;
  updated_at?: string;
  evidence?: Array<Record<string, unknown>>;
  timeline?: Array<Record<string, unknown>>;
  workflow_errors?: string[];
};

export const API_BASE =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) || "http://127.0.0.1:8000";

async function parseJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const t = await res.text();
    throw new Error(t || `Request failed (${res.status})`);
  }
  return (await res.json()) as T;
}

export type UserProfile = {
  id: string;
  rank: CertisRank;
  role_label: string;
  deployment_type: "ground" | "command_centre";
  assigned_zone: string | null;
  full_name: string | null;
  badge_id?: string | null;
};

export type DispatchPanelRow = {
  id: string;
  incident_id: string;
  instruction: string;
  dispatched_officer_role?: string | null;
  dispatched_by?: string | null;
  sent_at?: string | null;
  acknowledged?: boolean;
  acknowledged_at?: string | null;
  incident_type?: string | null;
  priority?: string | null;
  location?: string | null;
  incident_status?: string | null;
  assigned_zone?: string | null;
};

export type IncidentReportRow = {
  id: string;
  incident_id: string;
  report_text?: string | null;
  report_type?: string | null;
  generated_by?: string | null;
  generated_at?: string | null;
  submitted?: boolean;
  submitted_at?: string | null;
};

export type AuditLogEntry = {
  id: string;
  incident_id: string;
  actor?: string | null;
  action?: string | null;
  detail?: Record<string, unknown> | null;
  created_at?: string | null;
};

export type RiskPoint = {
  id: string;
  risk_score?: number | null;
  priority?: string | null;
  assigned_zone?: string | null;
  incident_type?: string | null;
  created_at?: string | null;
};

export type OfficerDailyTask = {
  id: string;
  task_date: string;
  officer_rank: string;
  zone?: string | null;
  task_type?: string | null;
  status?: string | null;
  description?: string | null;
  created_at?: string | null;
};

export async function fetchGroundIncidents(rank: string, zone?: string | null): Promise<{ incidents: Incident[] }> {
  const q = new URLSearchParams({ rank });
  if (zone) q.set("zone", zone);
  const res = await fetch(`${API_BASE}/dashboard/ground/incidents?${q}`);
  return parseJson(res);
}

export async function fetchGroundDispatches(rank: string): Promise<{ notifications: DispatchPanelRow[] }> {
  const res = await fetch(`${API_BASE}/dashboard/ground/dispatches?${new URLSearchParams({ rank })}`);
  return parseJson(res);
}

export async function acknowledgeDispatchNotification(notificationId: string): Promise<unknown> {
  const res = await fetch(`${API_BASE}/dashboard/ground/dispatches/${notificationId}/acknowledge`, {
    method: "POST",
  });
  return parseJson(res);
}

export async function fetchOfficerTodayTask(
  rank: string,
  zone?: string | null,
  taskDate?: string | null,
): Promise<{ task: OfficerDailyTask | null; task_date: string }> {
  const q = new URLSearchParams({ rank });
  if (zone) q.set("zone", zone);
  if (taskDate) q.set("task_date", taskDate);
  const res = await fetch(`${API_BASE}/dashboard/ground/today-task?${q}`);
  return parseJson(res);
}

export async function postManualTrigger(body: {
  location: string;
  incident_type_hint?: string | null;
  description?: string | null;
  user_id?: string | null;
}): Promise<{ incident_id: string; status: string; message: string }> {
  const res = await fetch(`${API_BASE}/dashboard/ground/manual-trigger`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return parseJson(res);
}

export async function fetchCcOpenIncidents(): Promise<{ incidents: Incident[] }> {
  const res = await fetch(`${API_BASE}/dashboard/cc/incidents`);
  return parseJson(res);
}

export async function fetchCcReviewQueue(): Promise<{ incidents: Incident[] }> {
  const res = await fetch(`${API_BASE}/dashboard/cc/review-queue`);
  return parseJson(res);
}

export async function fetchCcDispatchPanel(): Promise<{ rows: DispatchPanelRow[] }> {
  const res = await fetch(`${API_BASE}/dashboard/cc/dispatch-panel`);
  return parseJson(res);
}

export async function fetchCcZoneCounts(): Promise<{ zones: { zone: string; open_count: string | number }[] }> {
  const res = await fetch(`${API_BASE}/dashboard/cc/zones`);
  return parseJson(res);
}

export async function fetchCcReports(): Promise<{ reports: IncidentReportRow[] }> {
  const res = await fetch(`${API_BASE}/dashboard/cc/reports`);
  return parseJson(res);
}

export async function submitIncidentReport(reportId: string): Promise<unknown> {
  const res = await fetch(`${API_BASE}/dashboard/cc/reports/${reportId}/submit`, { method: "POST" });
  return parseJson(res);
}

export async function fetchSopChunksForIncident(
  incidentId: string,
): Promise<{ sop_chunks: Array<Record<string, unknown>>; state_json: Record<string, unknown> | null }> {
  const res = await fetch(`${API_BASE}/dashboard/cc/incidents/${incidentId}/sop-chunks`);
  return parseJson(res);
}

export async function fetchSupervisorAudit(incidentId: string): Promise<{ entries: AuditLogEntry[] }> {
  const res = await fetch(`${API_BASE}/dashboard/supervisor/audit/${incidentId}`);
  return parseJson(res);
}

export async function fetchSupervisorRiskPoints(): Promise<{ points: RiskPoint[] }> {
  const res = await fetch(`${API_BASE}/dashboard/supervisor/risk-points`);
  return parseJson(res);
}

export function shiftExportUrl(zone: string, shiftStartIso: string, shiftEndIso: string): string {
  const q = new URLSearchParams({
    shift_start: shiftStartIso,
    shift_end: shiftEndIso,
  });
  if (zone) q.set("zone", zone);
  return `${API_BASE}/dashboard/supervisor/shift-export?${q}`;
}

export async function getIncident(incidentId: string): Promise<Incident> {
  const res = await fetch(`${API_BASE}/incident/${incidentId}`);
  if (!res.ok) {
    throw new Error(`Failed to fetch incident (${res.status})`);
  }
  return (await res.json()) as Incident;
}

export async function submitHumanReview(params: {
  incidentId: string;
  status: "approved" | "rejected";
  reviewerId?: string;
  reviewerRank?: CertisRank | null;
}): Promise<Incident> {
  const res = await fetch(`${API_BASE}/incident/${params.incidentId}/review`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      human_review_status: params.status,
      human_reviewer_id: params.reviewerId || null,
      human_reviewer_rank: params.reviewerRank ?? null,
    }),
  });
  if (!res.ok) {
    throw new Error(`Failed to submit review (${res.status})`);
  }
  return (await res.json()) as Incident;
}
