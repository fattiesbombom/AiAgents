import { useMutation, useQueryClient } from "@tanstack/react-query";
import { submitHumanReview, type CertisRank, type Incident } from "../lib/api";

const RANK_OPTIONS: { value: CertisRank; label: string }[] = [
  { value: "SO", label: "Security Officer (SO)" },
  { value: "SSO", label: "Senior Security Officer (SSO)" },
  { value: "SS", label: "Security Supervisor (SS)" },
  { value: "SSS", label: "Senior Security Supervisor (SSS)" },
  { value: "CSO", label: "Chief Security Officer (CSO)" },
];

type Props = {
  incident: Incident;
  reviewerId: string;
  onReviewerIdChange: (v: string) => void;
  reviewerRank: CertisRank | "";
  onReviewerRankChange: (v: CertisRank | "") => void;
};

export function HumanReviewPanel({
  incident,
  reviewerId,
  onReviewerIdChange,
  reviewerRank,
  onReviewerRankChange,
}: Props) {
  const needsReview = incident.feed_source === "remote" && incident.human_review_status === "pending";
  const qc = useQueryClient();

  const mutation = useMutation({
    mutationFn: (status: "approved" | "rejected") =>
      submitHumanReview({
        incidentId: incident.id,
        status,
        reviewerId,
        reviewerRank: status === "approved" ? reviewerRank || undefined : undefined,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["incident", incident.id] });
    },
  });

  if (!needsReview) return null;

  return (
    <section className="card review-card">
      <h2>Human Review Required</h2>
      <p>
        Review required for remote source incidents. Check context, evidence, and current recommendation before making a decision.
      </p>

      <label className="label" htmlFor="reviewerId">
        Reviewer ID
      </label>
      <input
        id="reviewerId"
        className="input"
        value={reviewerId}
        onChange={(e) => onReviewerIdChange(e.target.value)}
        placeholder="your-user-id"
      />

      <label className="label" htmlFor="reviewerRank">
        Your rank (required to approve escalation)
      </label>
      <select
        id="reviewerRank"
        className="input"
        value={reviewerRank}
        onChange={(e) => onReviewerRankChange((e.target.value || "") as CertisRank | "")}
      >
        <option value="">Select rank…</option>
        {RANK_OPTIONS.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>

      {incident.can_approve_escalation === false && (
        <p className="subtle">
          This incident&apos;s originating responder cannot approve escalation. Approvals will be recorded as rejected.
        </p>
      )}

      <div className="actions">
        <button
          className="btn btn-approve"
          disabled={mutation.isPending || !reviewerRank}
          onClick={() => mutation.mutate("approved")}
        >
          Confirm with action
        </button>
        <button
          className="btn btn-reject"
          disabled={mutation.isPending}
          onClick={() => mutation.mutate("rejected")}
        >
          Don't confirm with action
        </button>
      </div>

      {mutation.isError && <p className="error">Failed to submit review. Check backend logs/MCP connectivity.</p>}
      {mutation.isSuccess && <p className="ok">Review submitted.</p>}
    </section>
  );
}
