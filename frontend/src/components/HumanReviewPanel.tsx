import { useMutation, useQueryClient } from "@tanstack/react-query";
import { submitHumanReview, type Incident } from "../lib/api";

type Props = {
  incident: Incident;
  reviewerId: string;
  onReviewerIdChange: (v: string) => void;
};

export function HumanReviewPanel({ incident, reviewerId, onReviewerIdChange }: Props) {
  const needsReview = incident.feed_source === "remote" && incident.human_review_status === "pending";
  const qc = useQueryClient();

  const mutation = useMutation({
    mutationFn: (status: "approved" | "rejected") =>
      submitHumanReview({ incidentId: incident.id, status, reviewerId }),
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

      <div className="actions">
        <button
          className="btn btn-approve"
          disabled={mutation.isPending}
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
