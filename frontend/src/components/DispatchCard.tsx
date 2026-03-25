import type { DispatchPanelRow } from "../lib/api";
import { PriorityBadge } from "./PriorityBadge";

type Props = {
  row: DispatchPanelRow;
  mode: "ground" | "cc";
  onAcknowledge?: (notificationId: string) => void;
  ackLoading?: boolean;
};

export function DispatchCard({ row, mode, onAcknowledge, ackLoading }: Props) {
  return (
    <div className={`dispatch-card ${row.acknowledged ? "dispatch-card--acked" : ""}`}>
      <p className="dispatch-card__instruction">{row.instruction || "—"}</p>
      <p className="subtle dispatch-card__meta">
        {row.location && <span>{row.location} · </span>}
        <PriorityBadge priority={row.priority} />
        {row.dispatched_officer_role && (
          <span>
            {" "}
            · To <strong>{row.dispatched_officer_role}</strong>
          </span>
        )}
      </p>
      {mode === "cc" && (
        <p className="dispatch-card__ack subtle">
          Ground acknowledgement:{" "}
          <strong>{row.acknowledged ? `Yes (${row.acknowledged_at || "recorded"})` : "Pending"}</strong>
        </p>
      )}
      {mode === "ground" && !row.acknowledged && onAcknowledge && (
        <button
          type="button"
          className="btn btn-primary dispatch-card__btn"
          disabled={ackLoading}
          onClick={() => onAcknowledge(row.id)}
        >
          {ackLoading ? "Acknowledging…" : "Acknowledge"}
        </button>
      )}
    </div>
  );
}
