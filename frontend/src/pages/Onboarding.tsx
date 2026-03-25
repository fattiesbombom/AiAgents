import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { isSupabaseConfigured, supabase } from "../lib/supabase";

type LocationState = {
  fullName?: string;
  roleLabel?: string;
  rank?: string;
  deploymentType?: string;
  pendingProfile?: boolean;
};

function dashboardBlurb(rank: string | undefined, deployment: string | undefined): string {
  const d = deployment === "command_centre" ? "command centre" : "ground";
  if (rank === "SO" || rank === "SSO") {
    return `Your dashboard focuses on tasks, dispatches, and incidents assigned to you as a ${d} officer. Remote incidents may require your review before escalation.`;
  }
  if (rank === "SS") {
    return "Your dashboard includes broader incident visibility, dispatch context, and tools aligned with supervisory duties in the SCC.";
  }
  return "Your dashboard will show incidents, reviews, and operational data according to your Certis profile and zone.";
}

export function Onboarding() {
  const navigate = useNavigate();
  const location = useLocation();
  const initial = (location.state ?? {}) as LocationState;

  const [fullName, setFullName] = useState(initial.fullName ?? "");
  const [roleLabel, setRoleLabel] = useState(initial.roleLabel ?? "");
  const [rank, setRank] = useState(initial.rank ?? "");
  const [deploymentType, setDeploymentType] = useState(initial.deploymentType ?? "");
  const [pendingProfile] = useState(Boolean(initial.pendingProfile));
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!isSupabaseConfigured()) {
        if (!cancelled) setLoading(false);
        return;
      }
      const { data: userRes } = await supabase.auth.getUser();
      const user = userRes.user;
      if (!user) {
        if (!cancelled) {
          setLoading(false);
          navigate("/login", { replace: true });
        }
        return;
      }

      const meta = user.user_metadata || {};
      setFullName((prev) => prev || (typeof meta.full_name === "string" ? meta.full_name : ""));
      setRoleLabel((prev) => prev || (typeof meta.role_label === "string" ? meta.role_label : ""));
      setRank((prev) => prev || (typeof meta.rank === "string" ? meta.rank : ""));
      setDeploymentType((prev) =>
        prev || (typeof meta.deployment_type === "string" ? meta.deployment_type : ""),
      );

      const { data: prof } = await supabase.from("profiles").select("*").eq("id", user.id).maybeSingle();
      if (!cancelled && prof) {
        setFullName((prev) => prev || (typeof prof.full_name === "string" ? prof.full_name : ""));
        setRoleLabel((prev) => prev || (typeof prof.role_label === "string" ? prof.role_label : ""));
        setRank((prev) => prev || (typeof prof.rank === "string" ? prof.rank : ""));
        setDeploymentType((prev) =>
          prev || (typeof prof.deployment_type === "string" ? prof.deployment_type : ""),
        );
      }
      if (!cancelled) setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [navigate]);

  const displayName = fullName || "officer";

  if (loading) {
    return (
      <div className="auth-page">
        <div className="auth-panel">
          <p className="subtle">Loading your profile…</p>
        </div>
      </div>
    );
  }

  return (
    <div className="auth-page">
      <div className="auth-panel">
        <div className="certis-brand">
          <span className="certis-brand__mark">Certis</span>
          <span className="certis-brand__sub">Welcome</span>
        </div>
        <h1 className="onboard-title">Welcome, {displayName}</h1>
        <p className="onboard-line">
          You are registered as <strong>{roleLabel || "Security Officer"}</strong>
          {rank ? ` (${rank})` : ""}.
        </p>
        {deploymentType && (
          <p className="subtle">
            Deployment:{" "}
            {deploymentType === "command_centre" ? "Command centre (SCC / FCC)" : "Ground (patrol / site)"}
          </p>
        )}
        <p className="onboard-body">{dashboardBlurb(rank, deploymentType)}</p>
        {pendingProfile && (
          <p className="ok">
            Your profile row is being created. If anything looks wrong, refresh this page in a few seconds.
          </p>
        )}
        <Link className="btn btn-accent onboard-cta" to="/dashboard">
          Go to my dashboard
        </Link>
      </div>
    </div>
  );
}
