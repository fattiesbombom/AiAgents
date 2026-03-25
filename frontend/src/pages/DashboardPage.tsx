import { useState } from "react";
import { useIncident } from "../hooks/useIncident";
import { HumanReviewPanel } from "../components/HumanReviewPanel";
import { IncidentDetails } from "../components/IncidentDetails";
import type { CertisRank } from "../lib/api";

export function DashboardPage() {
  const [incidentIdInput, setIncidentIdInput] = useState("");
  const [incidentId, setIncidentId] = useState("");
  const [reviewerId, setReviewerId] = useState("");
  const [reviewerRank, setReviewerRank] = useState<CertisRank | "">("");
  const query = useIncident(incidentId);

  return (
    <main className="container">
      <h1>Security Incident Dashboard</h1>
      <p className="subtle">Fetch an incident by ID and process human review when required.</p>

      <section className="card">
        <h2>Lookup Incident</h2>
        <div className="row">
          <input
            className="input"
            placeholder="incident UUID"
            value={incidentIdInput}
            onChange={(e) => setIncidentIdInput(e.target.value)}
          />
          <button className="btn" onClick={() => setIncidentId(incidentIdInput.trim())}>
            Load
          </button>
        </div>
      </section>

      {query.isLoading && <p>Loading incident...</p>}
      {query.isError && <p className="error">{(query.error as Error).message}</p>}

      {query.data && (
        <>
          <HumanReviewPanel
            incident={query.data}
            reviewerId={reviewerId}
            onReviewerIdChange={setReviewerId}
            reviewerRank={reviewerRank}
            onReviewerRankChange={setReviewerRank}
          />
          <IncidentDetails incident={query.data} />
        </>
      )}
    </main>
  );
}
