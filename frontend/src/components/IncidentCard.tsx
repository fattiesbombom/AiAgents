import type { Incident } from "../lib/api";
import { PriorityBadge } from "./PriorityBadge";

type Props = {
  incident: Pick<Incident, "id" | "incident_type" | "location" | "priority" | "incident_status"> &
    Partial<Incident>;
  selected?: boolean;
  onSelect?: (id: string) => void;
};

export function IncidentCard({ incident, selected, onSelect }: Props) {
  const isOfficerDown = (incident.incident_type || "").toLowerCase() === "officer_down";
  const typeLabel = isOfficerDown ? "OFFICER DOWN" : incident.incident_type || "Incident";
  const cardClass = [
    "incident-card",
    selected ? "incident-card--selected" : "",
    isOfficerDown ? "incident-card--officer-down" : "",
  ]
    .filter(Boolean)
    .join(" ");

  const inner = (
    <>
      <div className="incident-card__top">
        <span className={`incident-card__type ${isOfficerDown ? "incident-card__type--alert" : ""}`}>
          {typeLabel}
        </span>
        <PriorityBadge priority={incident.priority} />
      </div>
      <p className="incident-card__loc">{incident.location || "Location TBC"}</p>
      <p className="incident-card__meta subtle">
        {incident.incident_status || "—"} · {incident.id.slice(0, 8)}…
      </p>
    </>
  );

  if (onSelect) {
    return (
      <button type="button" className={cardClass} onClick={() => onSelect(incident.id)}>
        {inner}
      </button>
    );
  }

  return <div className={cardClass}>{inner}</div>;
}
