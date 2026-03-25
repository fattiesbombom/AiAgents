type Props = {
  node_name?: string | null;
  summary?: string | null;
  created_at?: string | null;
};

export function TimelineEntry({ node_name, summary, created_at }: Props) {
  const ts = created_at ? new Date(created_at).toLocaleString() : "—";
  return (
    <li className="timeline-entry">
      <div className="timeline-entry__head">
        <strong className="timeline-entry__node">{node_name || "node"}</strong>
        <span className="timeline-entry__ts subtle">{ts}</span>
      </div>
      <p className="timeline-entry__summary">{summary || "—"}</p>
    </li>
  );
}
