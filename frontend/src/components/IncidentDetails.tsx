import type { Incident } from "../lib/api";

type Props = { incident: Incident };

export function IncidentDetails({ incident }: Props) {
  return (
    <section className="card">
      <h2>Incident Details</h2>
      <div className="grid">
        <Info label="ID" value={incident.id} />
        <Info label="Type" value={incident.incident_type} />
        <Info label="Priority" value={incident.priority} />
        <Info label="Feed Source" value={incident.feed_source} />
        <Info label="Source Type" value={incident.source_type} />
        <Info label="Location" value={incident.location} />
        <Info label="Status" value={incident.incident_status} />
        <Info label="Confirmed" value={String(incident.confirmed)} />
        <Info label="Risk Score" value={incident.risk_score?.toFixed(2)} />
        <Info label="Police Notified" value={String(incident.police_notified)} />
        <Info label="Review Status" value={incident.human_review_status ?? undefined} />
        <Info label="Responder rank" value={incident.responder_rank ?? undefined} />
        <Info label="Responder role" value={incident.responder_role_label ?? undefined} />
        <Info label="Can approve escalation" value={String(incident.can_approve_escalation ?? false)} />
        <Info label="Reviewer rank" value={incident.human_reviewer_rank ?? undefined} />
        <Info label="Deployment" value={incident.deployment_type ?? undefined} />
      </div>

      <div className="spacer" />
      <h3>Recommended Action</h3>
      <p>{incident.recommended_action || "No recommendation yet."}</p>

      <div className="spacer" />
      <h3>Workflow Errors</h3>
      <ul>
        {(incident.workflow_errors || []).length === 0 ? (
          <li>None</li>
        ) : (
          (incident.workflow_errors || []).map((err, i) => <li key={`${err}-${i}`}>{err}</li>)
        )}
      </ul>
    </section>
  );
}

function Info({ label, value }: { label: string; value?: string }) {
  return (
    <div>
      <span className="label">{label}</span>
      <div>{value ?? "-"}</div>
    </div>
  );
}
