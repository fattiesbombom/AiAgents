import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";
import { useUserProfile } from "../hooks/useUserProfile";
import { isSupabaseConfigured } from "../lib/supabase";
import { LoadingSpinner } from "./LoadingSpinner";

type Props = { children: ReactNode };

export function ProtectedRoute({ children }: Props) {
  const { session, loading, error } = useUserProfile();

  if (!isSupabaseConfigured()) {
    return (
      <main className="container">
        <p className="error">Supabase is not configured.</p>
      </main>
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

  return <>{children}</>;
}
