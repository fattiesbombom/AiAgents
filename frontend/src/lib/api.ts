export type HumanReviewStatus = "pending" | "approved" | "rejected" | null;

export type Incident = {
  id: string;
  incident_type?: string;
  priority?: string;
  feed_source?: "live" | "remote";
  source_type?: "video" | "non_video";
  location?: string;
  confirmed?: boolean;
  risk_score?: number;
  recommended_action?: string;
  incident_status?: string;
  police_notified?: boolean;
  police_notification_type?: string | null;
  human_review_status?: HumanReviewStatus;
  created_at?: string;
  updated_at?: string;
  evidence?: Array<Record<string, unknown>>;
  timeline?: Array<Record<string, unknown>>;
  workflow_errors?: string[];
};

const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) || "http://127.0.0.1:8000";

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
}): Promise<Incident> {
  const res = await fetch(`${API_BASE}/incident/${params.incidentId}/review`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      human_review_status: params.status,
      human_reviewer_id: params.reviewerId || null,
    }),
  });
  if (!res.ok) {
    throw new Error(`Failed to submit review (${res.status})`);
  }
  return (await res.json()) as Incident;
}
