export function LoadingSpinner({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="db-loading" role="status" aria-live="polite">
      <div className="db-loading__spinner" aria-hidden />
      <p className="subtle">{label}</p>
    </div>
  );
}
