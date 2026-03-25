import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { coerceStaffRoleType, parseCertisRank, securityOfficerNeedsDailyAssignment } from "../lib/api";
import type { UserProfile } from "../lib/api";
import { isSupabaseConfigured, supabase } from "../lib/supabase";

function rowToProfile(row: Record<string, unknown>): UserProfile | null {
  if (!row || typeof row.id !== "string") return null;
  const ta = row.todays_assignment;
  const todays_assignment = ta === "ground" || ta === "command_centre" ? ta : null;
  const asg = row.assignment_set_at;
  const role_type = coerceStaffRoleType(row.role_type);
  const parsedRank = parseCertisRank(row.rank);
  const rank = parsedRank ?? (role_type === "security_officer" ? "SO" : null);
  return {
    id: String(row.id),
    role_type,
    rank,
    role_label: typeof row.role_label === "string" ? row.role_label : "Officer",
    deployment_type:
      row.deployment_type === "ground" || row.deployment_type === "command_centre"
        ? row.deployment_type
        : null,
    todays_assignment,
    assignment_set_at: typeof asg === "string" ? asg : null,
    assigned_zone: typeof row.assigned_zone === "string" ? row.assigned_zone : null,
    full_name: typeof row.full_name === "string" ? row.full_name : null,
    badge_id: typeof row.badge_id === "string" ? row.badge_id : null,
  };
}

function friendlyAuthError(message: string): string {
  const m = message.toLowerCase();
  if (m.includes("invalid login")) return "Invalid email or password.";
  if (m.includes("email not confirmed")) return "Please confirm your email before signing in.";
  return message;
}

export function Login() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!isSupabaseConfigured()) {
      setError("Supabase is not configured. Set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY.");
      return;
    }
    setLoading(true);
    try {
      const { error: signErr } = await supabase.auth.signInWithPassword({
        email: email.trim(),
        password,
      });
      if (signErr) {
        setError(friendlyAuthError(signErr.message));
        return;
      }
      const { data: userRes } = await supabase.auth.getUser();
      const uid = userRes.user?.id;
      if (!uid) {
        setError("Signed in but user session is missing.");
        return;
      }
      const { data: profRow, error: profErr } = await supabase.from("profiles").select("*").eq("id", uid).maybeSingle();
      if (profErr) {
        setError(profErr.message);
        return;
      }
      const profile = profRow && typeof profRow === "object" ? rowToProfile(profRow as Record<string, unknown>) : null;
      if (!profile) {
        navigate("/onboarding", { replace: true, state: { pendingProfile: true } });
        return;
      }
      if (securityOfficerNeedsDailyAssignment(profile)) {
        navigate("/daily-assignment", { replace: true });
      } else {
        navigate("/dashboard", { replace: true });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-page">
      <div className="auth-panel">
        <div className="certis-brand">
          <span className="certis-brand__mark">Certis</span>
          <span className="certis-brand__sub">Sign in</span>
        </div>
        {error && <p className="error">{error}</p>}
        <form onSubmit={submit}>
          <label className="label" htmlFor="li-email">
            Email
          </label>
          <input
            id="li-email"
            className="input"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="email"
            required
          />
          <label className="label" htmlFor="li-pass">
            Password
          </label>
          <input
            id="li-pass"
            className="input"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
          />
          <div className="auth-actions" style={{ marginTop: 16 }}>
            <button type="submit" className="btn btn-primary" disabled={loading}>
              {loading ? "Signing in…" : "Sign in"}
            </button>
          </div>
        </form>
        <p className="auth-footer subtle">
          New here?{" "}
          <Link className="auth-link" to="/signup">
            Create an account
          </Link>
        </p>
      </div>
    </div>
  );
}
