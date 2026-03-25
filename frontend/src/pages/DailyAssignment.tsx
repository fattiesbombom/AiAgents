import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { LoadingSpinner } from "../components/LoadingSpinner";
import { useUserProfile } from "../hooks/useUserProfile";
import { securityOfficerNeedsDailyAssignment } from "../lib/api";
import { isSupabaseConfigured, supabase } from "../lib/supabase";

export function DailyAssignment() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { profile, session, loading, error, refetch } = useUserProfile();
  const [choice, setChoice] = useState<"ground" | "command_centre" | null>(null);

  useEffect(() => {
    if (!loading && profile && !securityOfficerNeedsDailyAssignment(profile)) {
      navigate("/dashboard", { replace: true });
    }
  }, [loading, profile, navigate]);

  const saveMut = useMutation({
    mutationFn: async (assignment: "ground" | "command_centre") => {
      const { data: userRes } = await supabase.auth.getUser();
      const uid = userRes.user?.id;
      if (!uid) throw new Error("Not signed in.");
      const { error: upErr } = await supabase
        .from("profiles")
        .update({
          todays_assignment: assignment,
          assignment_set_at: new Date().toISOString(),
        })
        .eq("id", uid);
      if (upErr) throw upErr;
    },
    onSuccess: async () => {
      await refetch();
      await qc.invalidateQueries({ queryKey: ["profile"] });
      navigate("/dashboard", { replace: true });
    },
  });

  if (!isSupabaseConfigured()) {
    return (
      <div className="auth-page">
        <div className="auth-panel">
          <p className="error">Supabase is not configured.</p>
        </div>
      </div>
    );
  }

  if (loading) {
    return (
      <main className="container db-router-loading">
        <LoadingSpinner label="Loading…" />
      </main>
    );
  }

  if (error) {
    return (
      <main className="container">
        <p className="error">{error.message}</p>
      </main>
    );
  }

  if (!session) {
    return <Navigate to="/login" replace />;
  }

  if (!profile) {
    return (
      <main className="container">
        <p className="error">No profile found.</p>
      </main>
    );
  }

  if (profile.role_type !== "security_officer") {
    return <Navigate to="/dashboard" replace />;
  }

  const rank = profile.rank;
  const canCommandCentre = rank === "SSO" || rank === "SS" || rank === "SSS" || rank === "CSO";

  const todayStr = new Date().toLocaleDateString(undefined, {
    weekday: "long",
    year: "numeric",
    month: "long",
    day: "numeric",
  });

  return (
    <div className="auth-page">
      <div className="auth-panel auth-panel--wide">
        <div className="certis-brand">
          <span className="certis-brand__mark">Certis</span>
          <span className="certis-brand__sub">Start your shift</span>
        </div>
        <p className="subtle" style={{ marginBottom: 16 }}>
          Quick check-in — choose where you are working today.
        </p>

        {saveMut.isError && (
          <p className="error">{(saveMut.error as Error).message || "Could not save assignment."}</p>
        )}

        <div className="deploy-options">
          <button
            type="button"
            className={`deploy-card deploy-card--button ${choice === "ground" ? "deploy-card--selected" : ""}`}
            onClick={() => setChoice("ground")}
          >
            <span className="deploy-card__title">Ground officer</span>
            <span className="deploy-card__desc">
              On patrol · respond to incidents · body-worn camera active
            </span>
          </button>

          <div title={canCommandCentre ? undefined : "SSO rank required for command centre"}>
            <button
              type="button"
              disabled={!canCommandCentre}
              className={`deploy-card deploy-card--button ${choice === "command_centre" ? "deploy-card--selected" : ""}`}
              style={!canCommandCentre ? { opacity: 0.55, cursor: "not-allowed" } : undefined}
              onClick={() => canCommandCentre && setChoice("command_centre")}
            >
              <span className="deploy-card__title">Command centre</span>
              <span className="deploy-card__desc">
                SCC / FCC monitoring · dispatch · incident management
              </span>
            </button>
          </div>
        </div>

        <p className="subtle" style={{ marginTop: 20, textAlign: "center" }}>
          {todayStr}
        </p>

        <div className="auth-actions" style={{ justifyContent: "center", marginTop: 8 }}>
          <button
            type="button"
            className="btn btn-accent"
            disabled={!choice || saveMut.isPending}
            onClick={() => choice && saveMut.mutate(choice)}
          >
            {saveMut.isPending ? "Saving…" : "Start shift"}
          </button>
        </div>
      </div>
    </div>
  );
}
