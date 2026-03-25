import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { isSupabaseConfigured, supabase } from "../lib/supabase";

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
      const { data: prof } = await supabase.from("profiles").select("id").eq("id", uid).maybeSingle();
      if (prof?.id) {
        navigate("/dashboard", { replace: true });
      } else {
        navigate("/onboarding", { replace: true, state: { pendingProfile: true } });
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
