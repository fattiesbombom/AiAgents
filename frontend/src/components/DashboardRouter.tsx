import { lazy, Suspense, useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { useUserProfile } from "../hooks/useUserProfile";
import { isSupabaseConfigured, supabase } from "../lib/supabase";
import { LoadingSpinner } from "./LoadingSpinner";

const GroundOfficerDashboard = lazy(() =>
  import("../pages/GroundOfficerDashboard").then((m) => ({ default: m.GroundOfficerDashboard })),
);
const CommandCentreDashboard = lazy(() =>
  import("../pages/CommandCentreDashboard").then((m) => ({ default: m.CommandCentreDashboard })),
);

/** Only mounted when Supabase env is set — keeps heavy dashboard chunks (e.g. charts) off /login. */
function DashboardRouterInner() {
  const navigate = useNavigate();
  const { profile, session, loading, error } = useUserProfile();
  const [logoutBusy, setLogoutBusy] = useState(false);

  const onLogout = async () => {
    setLogoutBusy(true);
    try {
      if (isSupabaseConfigured()) {
        await supabase.auth.signOut();
      }
      navigate("/login", { replace: true });
    } finally {
      setLogoutBusy(false);
    }
  };

  if (loading) {
    return (
      <main className="container db-router-loading">
        <LoadingSpinner label="Loading your dashboard…" />
      </main>
    );
  }

  if (error) {
    return (
      <main className="container">
        <p className="error">{error.message}</p>
        <p className="subtle" style={{ marginTop: 8 }}>
          Check the browser console (F12). Common causes: wrong Supabase URL/key, or blocked requests.
        </p>
      </main>
    );
  }

  if (!session) {
    return <Navigate to="/login" replace />;
  }

  if (!profile) {
    return (
      <main className="container">
        <p className="error">No profile found for this account.</p>
        <p className="subtle">Complete onboarding or ask an administrator to provision your profile.</p>
      </main>
    );
  }

  const dash = (
    <Suspense
      fallback={
        <main className="container db-router-loading">
          <LoadingSpinner label="Loading dashboard…" />
        </main>
      }
    >
      {profile.deployment_type === "ground" ? (
        <GroundOfficerDashboard profile={profile} onLogout={onLogout} logoutLoading={logoutBusy} />
      ) : profile.deployment_type === "command_centre" ? (
        <CommandCentreDashboard profile={profile} onLogout={onLogout} logoutLoading={logoutBusy} />
      ) : (
        <Navigate to="/login" replace />
      )}
    </Suspense>
  );

  return dash;
}

export function DashboardRouter() {
  if (!isSupabaseConfigured()) {
    return (
      <main className="container">
        <p className="error">Supabase is not configured.</p>
        <p className="subtle">
          Create <code>frontend/.env</code> with <code>VITE_SUPABASE_URL</code> and{" "}
          <code>VITE_SUPABASE_ANON_KEY</code>, then restart Vite (<code>npm run dev</code>).
        </p>
        <p className="subtle" style={{ marginTop: 12 }}>
          Copy from <code>.env.example</code> if you have one.
        </p>
      </main>
    );
  }

  return <DashboardRouterInner />;
}
