import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { UserProfile } from "../lib/api";
import {
  fetchCcDispatchPanel,
  fetchCcOpenIncidents,
  fetchCcReports,
  fetchCcReviewQueue,
  fetchCcZoneCounts,
  fetchSupervisorAudit,
  fetchSupervisorRiskPoints,
  fetchSopChunksForIncident,
  getIncident,
  shiftExportUrl,
  submitHumanReview,
  submitIncidentReport,
  type Incident,
} from "../lib/api";
import { DashboardHeader } from "../components/DashboardHeader";
import { DispatchCard } from "../components/DispatchCard";
import { IncidentCard } from "../components/IncidentCard";
import { TimelineEntry } from "../components/TimelineEntry";
import { canSccApproveReview, isSupervisorRank } from "../components/RankBadge";

const REFETCH_MS = 10_000;

type Props = {
  profile: UserProfile;
  onLogout: () => void;
  logoutLoading?: boolean;
};

function needsHumanReview(inc: Incident): boolean {
  return (
    inc.feed_source === "remote" &&
    (inc.human_review_status === "pending" || inc.human_review_status == null)
  );
}

export function CommandCentreDashboard({ profile, onLogout, logoutLoading }: Props) {
  const qc = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const zone = profile.assigned_zone?.trim() || "";
  const ccRank = profile.rank ?? "SSO";

  const feedQ = useQuery({
    queryKey: ["dashboard", "cc", "incidents"],
    queryFn: fetchCcOpenIncidents,
    refetchInterval: REFETCH_MS,
  });

  const reviewQ = useQuery({
    queryKey: ["dashboard", "cc", "review-queue"],
    queryFn: fetchCcReviewQueue,
    refetchInterval: REFETCH_MS,
  });

  const dispatchQ = useQuery({
    queryKey: ["dashboard", "cc", "dispatch-panel"],
    queryFn: fetchCcDispatchPanel,
    refetchInterval: REFETCH_MS,
  });

  const zonesQ = useQuery({
    queryKey: ["dashboard", "cc", "zones"],
    queryFn: fetchCcZoneCounts,
    refetchInterval: REFETCH_MS,
  });

  const reportsQ = useQuery({
    queryKey: ["dashboard", "cc", "reports"],
    queryFn: fetchCcReports,
    refetchInterval: REFETCH_MS,
  });

  const detailQ = useQuery({
    queryKey: ["incident", selectedId],
    queryFn: () => getIncident(selectedId!),
    enabled: Boolean(selectedId),
    refetchInterval: REFETCH_MS,
  });

  const sopQ = useQuery({
    queryKey: ["dashboard", "cc", "sop", selectedId],
    queryFn: () => fetchSopChunksForIncident(selectedId!),
    enabled: Boolean(selectedId),
    refetchInterval: REFETCH_MS,
  });

  const auditQ = useQuery({
    queryKey: ["dashboard", "supervisor", "audit", selectedId],
    queryFn: () => fetchSupervisorAudit(selectedId!),
    enabled: Boolean(selectedId) && isSupervisorRank(ccRank),
    refetchInterval: REFETCH_MS,
  });

  const riskQ = useQuery({
    queryKey: ["dashboard", "supervisor", "risk"],
    queryFn: fetchSupervisorRiskPoints,
    enabled: isSupervisorRank(ccRank),
    refetchInterval: REFETCH_MS,
  });

  const reviewMut = useMutation({
    mutationFn: (p: { incidentId: string; status: "approved" | "rejected" }) =>
      submitHumanReview({
        incidentId: p.incidentId,
        status: p.status,
        reviewerId: profile.id,
        reviewerRank: p.status === "approved" ? ccRank : null,
      }),
    onSuccess: (_, v) => {
      void qc.invalidateQueries({ queryKey: ["dashboard", "cc", "review-queue"] });
      void qc.invalidateQueries({ queryKey: ["incident", v.incidentId] });
      void qc.invalidateQueries({ queryKey: ["dashboard", "cc", "incidents"] });
    },
  });

  const reportSubmitMut = useMutation({
    mutationFn: (reportId: string) => submitIncidentReport(reportId),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["dashboard", "cc", "reports"] }),
  });

  const chartData = useMemo(() => {
    const pts = riskQ.data?.points ?? [];
    return pts.slice(0, 24).map((p) => ({
      label: p.id.replace(/-/g, "").slice(0, 6),
      score: typeof p.risk_score === "number" ? p.risk_score : 0,
    }));
  }, [riskQ.data?.points]);

  const shiftEnd = new Date();
  const shiftStart = new Date(shiftEnd.getTime() - 8 * 3600 * 1000);
  const exportHref = shiftExportUrl(zone, shiftStart.toISOString(), shiftEnd.toISOString());

  const detail = detailQ.data;
  const timeline = (detail?.timeline ?? []) as Array<{
    node_name?: string;
    summary?: string;
    created_at?: string;
  }>;
  const sopChunks = sopQ.data?.sop_chunks ?? [];

  const canApprove = canSccApproveReview(ccRank);
  const supervisor = isSupervisorRank(ccRank);

  return (
    <main className="db-page">
      <DashboardHeader
        profile={profile}
        title="Command centre"
        subtitle="Live feed, review queue, dispatch picture, and incident tooling"
        onLogout={onLogout}
        logoutLoading={logoutLoading}
      />

      <div className="db-grid db-grid--cc">
        <section className="card db-panel db-panel--wide">
          <h2>Live incident feed</h2>
          <p className="subtle">Open incidents across all zones (priority order: critical → low).</p>
          {feedQ.isError && <p className="error">{(feedQ.error as Error).message}</p>}
          {(feedQ.data?.incidents ?? []).length === 0 && !feedQ.isLoading && (
            <p className="subtle">No open incidents.</p>
          )}
          <div className="db-feed">
            {(feedQ.data?.incidents ?? []).map((inc) => (
              <IncidentCard
                key={inc.id}
                incident={inc}
                selected={selectedId === inc.id}
                onSelect={setSelectedId}
              />
            ))}
          </div>
        </section>

        <section className="card db-panel">
          <h2>Zone overview</h2>
          <p className="subtle">Active open incidents per zone.</p>
          {zonesQ.isError && <p className="error">{(zonesQ.error as Error).message}</p>}
          <div className="db-zone-grid">
            {(zonesQ.data?.zones ?? []).length === 0 && !zonesQ.isLoading && (
              <p className="subtle">No zoned incidents.</p>
            )}
            {(zonesQ.data?.zones ?? []).map((z) => (
              <div key={z.zone} className="db-zone-tile">
                <span className="db-zone-tile__name">{z.zone}</span>
                <span className="db-zone-tile__count">{z.open_count}</span>
              </div>
            ))}
          </div>
        </section>

        <section className="card db-panel db-panel--wide">
          <h2>Human review queue</h2>
          <p className="subtle">
            Remote incidents awaiting decision. SSO: read-only; SS+ can approve or reject escalation.
          </p>
          {reviewQ.isError && <p className="error">{(reviewQ.error as Error).message}</p>}
          {(reviewQ.data?.incidents ?? []).length === 0 && !reviewQ.isLoading && (
            <p className="subtle">Queue is empty.</p>
          )}
          <div className="db-stack">
            {(reviewQ.data?.incidents ?? []).map((inc) => (
              <div key={inc.id} className="review-queue-row card review-card">
                <IncidentCard incident={inc} selected={selectedId === inc.id} onSelect={setSelectedId} />
                {needsHumanReview(inc) && (
                  <div className="review-queue-row__actions">
                    {!canApprove && (
                      <p className="subtle">Read-only — supervisor (SS+) action required.</p>
                    )}
                    {canApprove && (
                      <div className="actions">
                        <button
                          type="button"
                          className="btn btn-approve"
                          disabled={reviewMut.isPending}
                          onClick={() => reviewMut.mutate({ incidentId: inc.id, status: "approved" })}
                        >
                          Approve
                        </button>
                        <button
                          type="button"
                          className="btn btn-reject"
                          disabled={reviewMut.isPending}
                          onClick={() => reviewMut.mutate({ incidentId: inc.id, status: "rejected" })}
                        >
                          Reject
                        </button>
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        </section>

        <section className="card db-panel db-panel--wide">
          <h2>Dispatch panel</h2>
          <p className="subtle">Instructions issued to ground officers and acknowledgement status.</p>
          {dispatchQ.isError && <p className="error">{(dispatchQ.error as Error).message}</p>}
          {(dispatchQ.data?.rows ?? []).length === 0 && !dispatchQ.isLoading && (
            <p className="subtle">No dispatch rows.</p>
          )}
          <div className="db-stack">
            {(dispatchQ.data?.rows ?? []).map((row) => (
              <DispatchCard key={row.id} row={row} mode="cc" />
            ))}
          </div>
        </section>

        <section className="card db-panel db-panel--wide">
          <h2>Selected incident detail</h2>
          {!selectedId && <p className="subtle">Select an incident from the live feed.</p>}
          {selectedId && detailQ.isError && <p className="error">{(detailQ.error as Error).message}</p>}
          {selectedId && detail && (
            <>
              <p>
                <strong>{detail.incident_type}</strong> · {detail.location} · {detail.incident_status}
              </p>
              <details open className="db-details">
                <summary>Incident timeline (workflow nodes)</summary>
                {timeline.length === 0 && <p className="subtle">No timeline entries yet.</p>}
                <ul className="timeline-list">
                  {timeline.map((e, i) => (
                    <TimelineEntry
                      key={`${e.node_name}-${i}`}
                      node_name={e.node_name}
                      summary={e.summary}
                      created_at={e.created_at}
                    />
                  ))}
                </ul>
              </details>
              <details open className="db-details">
                <summary>SOP chunks (retrieved for this incident)</summary>
                {sopQ.isError && <p className="error">{(sopQ.error as Error).message}</p>}
                {sopChunks.length === 0 && !sopQ.isLoading && (
                  <p className="subtle">No SOP chunks stored for this incident yet.</p>
                )}
                <ul className="sop-chunk-list">
                  {sopChunks.map((c, i) => (
                    <li key={i} className="sop-chunk">
                      <strong>{String((c as { title?: string }).title ?? "Chunk")}</strong>
                      <p className="subtle">{(c as { content?: string }).content ?? JSON.stringify(c)}</p>
                    </li>
                  ))}
                </ul>
              </details>
            </>
          )}
        </section>

        <section className="card db-panel db-panel--wide">
          <h2>Incident reports</h2>
          <p className="subtle">Generated narratives — submit to mark as formally filed.</p>
          {reportsQ.isError && <p className="error">{(reportsQ.error as Error).message}</p>}
          {(reportsQ.data?.reports ?? []).length === 0 && !reportsQ.isLoading && (
            <p className="subtle">No reports yet.</p>
          )}
          <div className="db-stack">
            {(reportsQ.data?.reports ?? []).map((r) => (
              <div key={r.id} className="report-row">
                <p className="subtle">
                  {r.report_type || "report"} · {r.incident_id.slice(0, 8)}… ·{" "}
                  {r.submitted ? "Submitted" : "Draft"}
                </p>
                <p>{(r.report_text || "").slice(0, 200)}{(r.report_text?.length ?? 0) > 200 ? "…" : ""}</p>
                {!r.submitted && (
                  <button
                    type="button"
                    className="btn btn-primary"
                    disabled={reportSubmitMut.isPending}
                    onClick={() => reportSubmitMut.mutate(r.id)}
                  >
                    Submit
                  </button>
                )}
              </div>
            ))}
          </div>
        </section>

        {supervisor && (
          <section className="card db-panel db-panel--full supervisor-panel">
            <h2>Supervisor tools</h2>
            <p className="subtle">SS / SSS / CSO — audit trail, escalation approval, shift export, risk trend.</p>

            <div className="db-supervisor-grid">
              <div>
                <h3>Risk scores (24h)</h3>
                {riskQ.isError && <p className="error">{(riskQ.error as Error).message}</p>}
                {chartData.length === 0 && !riskQ.isLoading && (
                  <p className="subtle">No incidents with scores in the last 24 hours.</p>
                )}
                {chartData.length > 0 && (
                  <div className="db-chart-wrap">
                    <ResponsiveContainer width="100%" height={220}>
                      <BarChart data={chartData}>
                        <XAxis dataKey="label" tick={{ fill: "#98a4d4", fontSize: 10 }} />
                        <YAxis tick={{ fill: "#98a4d4", fontSize: 10 }} />
                        <Tooltip
                          contentStyle={{ background: "#131a30", border: "1px solid #2a3358" }}
                          labelStyle={{ color: "#f5f7ff" }}
                        />
                        <Bar dataKey="score" fill="#e85d04" radius={[4, 4, 0, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                )}
              </div>

              <div>
                <h3>Shift summary export</h3>
                <p className="subtle">Download JSON of incidents in your zone for the last 8 hours (browser download).</p>
                <a className="btn btn-accent db-download-link" href={exportHref} target="_blank" rel="noreferrer">
                  Generate &amp; download
                </a>
              </div>

              <div className="supervisor-panel__audit">
                <h3>Audit log</h3>
                {!selectedId && <p className="subtle">Select an incident to load its audit trail.</p>}
                {selectedId && auditQ.isError && <p className="error">{(auditQ.error as Error).message}</p>}
                {selectedId && (auditQ.data?.entries ?? []).length === 0 && !auditQ.isLoading && (
                  <p className="subtle">No audit entries.</p>
                )}
                <ul className="audit-list">
                  {(auditQ.data?.entries ?? []).map((e) => (
                    <li key={e.id} className="audit-row subtle">
                      <strong>{e.action}</strong> · {e.actor} · {e.created_at}
                      {e.detail && <pre className="audit-detail">{JSON.stringify(e.detail, null, 0)}</pre>}
                    </li>
                  ))}
                </ul>
              </div>

              <div>
                <h3>Approve escalation</h3>
                <p className="subtle">Uses human-review approval when escalation authority applies.</p>
                {!selectedId && <p className="subtle">Select an incident first.</p>}
                {detail && (
                  <>
                    <p className="subtle">
                      can_approve_escalation: {String(detail.can_approve_escalation)} · review:{" "}
                      {detail.human_review_status ?? "—"}
                    </p>
                    <button
                      type="button"
                      className="btn btn-approve"
                      title={
                        !canApprove
                          ? "Requires SS rank or above (SSO is view-only for approvals)"
                          : undefined
                      }
                      disabled={
                        !canApprove ||
                        reviewMut.isPending ||
                        !detail.can_approve_escalation ||
                        detail.human_review_status !== "pending"
                      }
                      onClick={() => selectedId && reviewMut.mutate({ incidentId: selectedId, status: "approved" })}
                    >
                      Approve escalation
                    </button>
                  </>
                )}
              </div>
            </div>
          </section>
        )}
      </div>
    </main>
  );
}
