import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import type { UserProfile } from "../lib/api";
import {
  acknowledgeDispatchNotification,
  fetchGroundDispatches,
  fetchGroundIncidents,
  fetchOfficerTodayTask,
  postManualTrigger,
} from "../lib/api";
import { DashboardHeader } from "../components/DashboardHeader";
import { DispatchCard } from "../components/DispatchCard";
import { IncidentCard } from "../components/IncidentCard";

const REFETCH_MS = 10_000;

type Props = {
  profile: UserProfile;
  onLogout: () => void;
  logoutLoading?: boolean;
};

export function GroundOfficerDashboard({ profile, onLogout, logoutLoading }: Props) {
  const qc = useQueryClient();
  const zone = profile.assigned_zone?.trim() || null;
  const [manualLoc, setManualLoc] = useState("");
  const [manualHint, setManualHint] = useState("");
  const [manualDesc, setManualDesc] = useState("");
  const [manualOk, setManualOk] = useState<string | null>(null);

  const incidentsQ = useQuery({
    queryKey: ["dashboard", "ground", "incidents", profile.rank, zone],
    queryFn: () => fetchGroundIncidents(profile.rank, zone),
    refetchInterval: REFETCH_MS,
  });

  const dispatchesQ = useQuery({
    queryKey: ["dashboard", "ground", "dispatches", profile.rank],
    queryFn: () => fetchGroundDispatches(profile.rank),
    refetchInterval: REFETCH_MS,
  });

  const taskQ = useQuery({
    queryKey: ["dashboard", "ground", "task", profile.rank, zone],
    queryFn: () => fetchOfficerTodayTask(profile.rank, zone),
    refetchInterval: REFETCH_MS,
  });

  const ackMut = useMutation({
    mutationFn: (id: string) => acknowledgeDispatchNotification(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["dashboard", "ground", "dispatches"] });
    },
  });

  const manualMut = useMutation({
    mutationFn: () =>
      postManualTrigger({
        location: manualLoc.trim(),
        incident_type_hint: manualHint.trim() || null,
        description: manualDesc.trim() || null,
        user_id: profile.id,
      }),
    onSuccess: (data) => {
      setManualOk(`Report logged. Incident ${data.incident_id.slice(0, 8)}… queued.`);
      setManualLoc("");
      setManualHint("");
      setManualDesc("");
      void qc.invalidateQueries({ queryKey: ["dashboard", "ground", "incidents"] });
    },
  });

  const incidents = incidentsQ.data?.incidents ?? [];
  const notifications = dispatchesQ.data?.notifications ?? [];
  const task = taskQ.data?.task;

  return (
    <main className="db-page">
      <DashboardHeader
        profile={profile}
        title="Ground operations"
        subtitle="Active dispatches, today’s task, and quick field reports"
        onLogout={onLogout}
        logoutLoading={logoutLoading}
      />

      <div className="db-grid db-grid--ground">
        <section className="card db-panel">
          <h2>My active incidents</h2>
          <p className="subtle">Dispatched to your rank{zone ? ` in zone ${zone}` : ""}.</p>
          {incidentsQ.isError && <p className="error">{(incidentsQ.error as Error).message}</p>}
          {incidents.length === 0 && !incidentsQ.isLoading && (
            <p className="subtle">No open incidents currently assigned to you.</p>
          )}
          <div className="db-stack">
            {incidents.map((inc) => (
              <IncidentCard key={inc.id} incident={inc} />
            ))}
          </div>
        </section>

        <section className="card db-panel">
          <h2>Current task</h2>
          <p className="subtle">Today’s routine entry from the work schedule (output DB).</p>
          {taskQ.isError && <p className="error">{(taskQ.error as Error).message}</p>}
          {!task && !taskQ.isLoading && (
            <p className="subtle">No scheduled task for {taskQ.data?.task_date ?? "today"}.</p>
          )}
          {task && (
            <div>
              <p>
                <strong>{task.task_type || "Routine task"}</strong> — {task.status || "scheduled"}
              </p>
              {task.description && <p className="subtle">{task.description}</p>}
            </div>
          )}
        </section>

        <section className="card db-panel">
          <h2>Dispatch notifications</h2>
          <p className="subtle">Unacknowledged instructions from the command centre.</p>
          {dispatchesQ.isError && <p className="error">{(dispatchesQ.error as Error).message}</p>}
          {notifications.length === 0 && !dispatchesQ.isLoading && (
            <p className="subtle">You’re all caught up — no pending dispatches.</p>
          )}
          <div className="db-stack">
            {notifications.map((row) => (
              <DispatchCard
                key={row.id}
                row={row}
                mode="ground"
                onAcknowledge={(id) => ackMut.mutate(id)}
                ackLoading={ackMut.isPending}
              />
            ))}
          </div>
        </section>

        <section className="card db-panel">
          <h2>Quick incident report</h2>
          <p className="subtle">Submit a manual field report (starts workflow with source_type manual_trigger).</p>
          {manualOk && <p className="ok">{manualOk}</p>}
          {manualMut.isError && <p className="error">{(manualMut.error as Error).message}</p>}
          <label className="label" htmlFor="g-loc">
            Location
          </label>
          <input
            id="g-loc"
            className="input"
            value={manualLoc}
            onChange={(e) => setManualLoc(e.target.value)}
            placeholder="e.g. Block A — Level 2"
          />
          <label className="label" htmlFor="g-hint">
            Incident type hint <span className="subtle">(optional)</span>
          </label>
          <input
            id="g-hint"
            className="input"
            value={manualHint}
            onChange={(e) => setManualHint(e.target.value)}
            placeholder="e.g. intrusion"
          />
          <label className="label" htmlFor="g-desc">
            Short description <span className="subtle">(optional)</span>
          </label>
          <textarea
            id="g-desc"
            className="input"
            rows={3}
            value={manualDesc}
            onChange={(e) => setManualDesc(e.target.value)}
            placeholder="What did you observe?"
          />
          <div className="actions">
            <button
              type="button"
              className="btn btn-accent"
              disabled={manualMut.isPending || !manualLoc.trim()}
              onClick={() => manualMut.mutate()}
            >
              {manualMut.isPending ? "Submitting…" : "Submit report"}
            </button>
          </div>
        </section>
      </div>
    </main>
  );
}
