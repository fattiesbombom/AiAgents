import type { Incident } from "../lib/api";

const PRIORITY_CLASS: Record<string, string> = {
  critical: "priority-badge priority-badge--critical",
  high: "priority-badge priority-badge--high",
  medium: "priority-badge priority-badge--medium",
  low: "priority-badge priority-badge--low",
};

type Props = { priority?: string | null };

export function PriorityBadge({ priority }: Props) {
  const p = (priority || "unknown").toLowerCase();
  const cls = PRIORITY_CLASS[p] ?? "priority-badge priority-badge--unknown";
  return <span className={cls}>{priority || "—"}</span>;
}

export function prioritySortKey(priority: Incident["priority"]): number {
  const p = (priority || "").toLowerCase();
  const order: Record<string, number> = { critical: 1, high: 2, medium: 3, low: 4 };
  return order[p] ?? 5;
}
