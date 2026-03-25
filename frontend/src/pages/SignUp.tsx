import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { RankSelector } from "../components/RankSelector";
import type { CertisRank } from "../components/rankData";
import { roleLabelForRank } from "../components/rankData";
import type { StaffRoleType } from "../lib/api";
import { isSupabaseConfigured, supabase } from "../lib/supabase";

type Step = 1 | 2 | 3 | 4;

function scorePassword(pw: string): 0 | 1 | 2 | 3 {
  if (!pw) return 0;
  if (pw.length < 8) return 1;
  const hasNum = /\d/.test(pw);
  const hasLet = /[a-zA-Z]/.test(pw);
  const hasSpec = /[^a-zA-Z0-9]/.test(pw);
  if (pw.length >= 10 && hasNum && hasLet && hasSpec) return 3;
  if (pw.length >= 8 && hasNum && hasLet) return 2;
  return 1;
}

function friendlyAuthError(message: string): string {
  const m = message.toLowerCase();
  if (m.includes("already registered") || m.includes("already been registered")) {
    return "This email is already registered. Try signing in instead.";
  }
  if (m.includes("password")) return "Password does not meet Supabase security rules. Try a stronger password.";
  if (m.includes("invalid email")) return "Please enter a valid email address.";
  return message;
}

const ROLE_CARDS: {
  id: StaffRoleType;
  title: string;
  description: string;
}[] = [
  {
    id: "security_officer",
    title: "Security Officer",
    description: "Ranks SO to CSO · daily assignment required",
  },
  {
    id: "auxiliary_police",
    title: "Auxiliary Police Officer",
    description: "Armed/unarmed · fixed ground role",
  },
  {
    id: "enforcement_officer",
    title: "Enforcement Officer",
    description: "Island-wide operations · fixed ground role",
  },
];

export function SignUp() {
  const navigate = useNavigate();
  const [step, setStep] = useState<Step>(1);
  const [roleType, setRoleType] = useState<StaffRoleType | null>(null);
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [badgeId, setBadgeId] = useState("");
  const [rank, setRank] = useState<CertisRank | null>(null);
  const [deployment, setDeployment] = useState<"ground" | "command_centre" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const isSecurityFlow = roleType === "security_officer";
  const maxStep = isSecurityFlow ? 4 : 2;
  const pwScore = useMemo(() => scorePassword(password), [password]);
  const pwLabel = ["", "Weak", "Medium", "Strong"][pwScore];

  const validatePersonal = () => {
    if (!fullName.trim()) {
      setError("Please enter your full name.");
      return false;
    }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) {
      setError("Please enter a valid email address.");
      return false;
    }
    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return false;
    }
    if (!/\d/.test(password) || !/[a-zA-Z]/.test(password)) {
      setError("Password must include at least one letter and one number.");
      return false;
    }
    return true;
  };

  const validateRank = () => {
    if (!rank) {
      setError("Please select your rank to continue.");
      return false;
    }
    return true;
  };

  const validateDeployment = () => {
    if (!deployment) {
      setError("Please choose your deployment type.");
      return false;
    }
    return true;
  };

  const goNext = () => {
    setError(null);
    if (step === 1 && !roleType) {
      setError("Please select a role type.");
      return;
    }
    if (step === 1 && roleType) setStep(2);
    else if (step === 2 && validatePersonal()) {
      if (isSecurityFlow) setStep(3);
      else void submitApoEo();
    } else if (step === 3 && validateRank()) setStep(4);
  };

  const goBack = () => {
    setError(null);
    if (step === 2) setStep(1);
    else if (step === 3) setStep(2);
    else if (step === 4) setStep(3);
  };

  const buildMetadataSecurity = () => {
    if (!rank || !deployment) return null;
    const roleLabel = roleLabelForRank(rank);
    return {
      full_name: fullName.trim(),
      role_type: "security_officer" as const,
      rank,
      role_label: roleLabel,
      deployment_type: deployment,
      badge_id: badgeId.trim() || undefined,
    };
  };

  const submitApoEo = async () => {
    if (!roleType || roleType === "security_officer") return;
    if (!validatePersonal()) return;
    if (!isSupabaseConfigured()) {
      setError("Supabase is not configured. Set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY in .env.");
      return;
    }

    setLoading(true);
    try {
      const role_label =
        roleType === "auxiliary_police" ? "Auxiliary Police Officer" : "Enforcement Officer";
      const { data, error: signErr } = await supabase.auth.signUp({
        email: email.trim(),
        password,
        options: {
          data: {
            full_name: fullName.trim(),
            role_type: roleType,
            role_label,
            badge_id: badgeId.trim() || undefined,
          },
        },
      });

      if (signErr) {
        setError(friendlyAuthError(signErr.message));
        setLoading(false);
        return;
      }

      if (!data.user?.id) {
        setError("Sign-up did not return a user. Check email confirmation settings in Supabase.");
        setLoading(false);
        return;
      }

      const { data: prof, error: profErr } = await supabase
        .from("profiles")
        .select("id")
        .eq("id", data.user.id)
        .maybeSingle();

      if (profErr) {
        console.warn("Profile fetch after sign-up:", profErr.message);
      }

      if (prof?.id) {
        navigate("/dashboard", { replace: true });
      } else {
        navigate("/onboarding", {
          replace: true,
          state: {
            fullName: fullName.trim(),
            roleLabel: role_label,
            roleType,
            pendingProfile: true,
          },
        });
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong.");
    } finally {
      setLoading(false);
    }
  };

  const submitSecurity = async () => {
    setError(null);
    if (!validateDeployment() || !rank || !deployment) return;
    if (!isSupabaseConfigured()) {
      setError("Supabase is not configured. Set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY in .env.");
      return;
    }

    const meta = buildMetadataSecurity();
    if (!meta) return;

    setLoading(true);
    try {
      const { data, error: signErr } = await supabase.auth.signUp({
        email: email.trim(),
        password,
        options: { data: meta },
      });

      if (signErr) {
        setError(friendlyAuthError(signErr.message));
        setLoading(false);
        return;
      }

      if (!data.user?.id) {
        setError("Sign-up did not return a user. Check email confirmation settings in Supabase.");
        setLoading(false);
        return;
      }

      const { data: prof, error: profErr } = await supabase
        .from("profiles")
        .select("id")
        .eq("id", data.user.id)
        .maybeSingle();

      if (profErr) {
        console.warn("Profile fetch after sign-up:", profErr.message);
      }

      const roleLabel = roleLabelForRank(rank);

      if (prof?.id) {
        navigate("/dashboard", { replace: true });
      } else {
        navigate("/onboarding", {
          replace: true,
          state: {
            fullName: fullName.trim(),
            roleLabel,
            rank,
            deploymentType: deployment,
            roleType: "security_officer",
            pendingProfile: true,
          },
        });
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong.");
    } finally {
      setLoading(false);
    }
  };

  if (!isSupabaseConfigured()) {
    return (
      <div className="auth-page">
        <div className="auth-panel">
          <div className="certis-brand">
            <span className="certis-brand__mark">Certis</span>
            <span className="certis-brand__sub">Security Operations</span>
          </div>
          <p className="error">
            Add <code>VITE_SUPABASE_URL</code> and <code>VITE_SUPABASE_ANON_KEY</code> to your frontend{" "}
            <code>.env</code> file, then restart Vite.
          </p>
          <Link className="auth-link" to="/login">
            Back to sign in
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="auth-page">
      <div className="auth-panel auth-panel--wide">
        <div className="certis-brand">
          <span className="certis-brand__mark">Certis</span>
          <span className="certis-brand__sub">Create your account</span>
        </div>

        <div className="step-indicator">
          {Array.from({ length: maxStep }, (_, i) => i + 1).map((n, idx) => (
            <span key={n}>
              {idx > 0 && <span className="step-indicator__line" />}
              <span className={step >= n ? "step-indicator__dot step-indicator__dot--on" : "step-indicator__dot"}>
                {n}
              </span>
            </span>
          ))}
        </div>

        {error && <p className="error">{error}</p>}

        {step === 1 && (
          <div className="auth-step">
            <h2 className="auth-step__title">Role type</h2>
            <p className="subtle auth-step__hint">Choose the category that matches your posting.</p>
            <div className="deploy-options deploy-options--three">
              {ROLE_CARDS.map((c) => (
                <button
                  key={c.id}
                  type="button"
                  className={`deploy-card deploy-card--button ${roleType === c.id ? "deploy-card--selected" : ""}`}
                  onClick={() => {
                    setRoleType(c.id);
                    setError(null);
                  }}
                >
                  <span className="deploy-card__title">{c.title}</span>
                  <span className="deploy-card__desc">{c.description}</span>
                </button>
              ))}
            </div>
            <div className="auth-actions">
              <button type="button" className="btn btn-primary" onClick={goNext}>
                Continue
              </button>
            </div>
          </div>
        )}

        {step === 2 && (
          <div className="auth-step">
            <h2 className="auth-step__title">Personal details</h2>
            <label className="label" htmlFor="su-name">
              Full name
            </label>
            <input
              id="su-name"
              className="input"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              autoComplete="name"
            />
            <label className="label" htmlFor="su-email">
              Email
            </label>
            <input
              id="su-email"
              className="input"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
            />
            <label className="label" htmlFor="su-pass">
              Password
            </label>
            <input
              id="su-pass"
              className="input"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="new-password"
            />
            <div className="pw-strength" aria-live="polite">
              <span className="subtle">Strength: {pwLabel || "—"}</span>
              <div className="pw-strength__bars">
                <div className={`pw-strength__bar pw-strength__bar--${pwScore >= 1 ? "on" : "off"} pw-strength__bar--c1`} />
                <div className={`pw-strength__bar pw-strength__bar--${pwScore >= 2 ? "on" : "off"} pw-strength__bar--c2`} />
                <div className={`pw-strength__bar pw-strength__bar--${pwScore >= 3 ? "on" : "off"} pw-strength__bar--c3`} />
              </div>
            </div>
            <label className="label" htmlFor="su-badge">
              Badge ID <span className="subtle">(optional)</span>
            </label>
            <input
              id="su-badge"
              className="input"
              value={badgeId}
              onChange={(e) => setBadgeId(e.target.value)}
              autoComplete="off"
            />
            <div className="auth-actions">
              <button type="button" className="btn btn-ghost" onClick={goBack}>
                Back
              </button>
              <button
                type="button"
                className="btn btn-primary"
                disabled={loading}
                onClick={() => void goNext()}
              >
                {isSecurityFlow ? "Continue" : loading ? "Creating account…" : "Create account"}
              </button>
            </div>
          </div>
        )}

        {step === 3 && isSecurityFlow && (
          <div className="auth-step">
            <h2 className="auth-step__title">Select your rank</h2>
            <p className="subtle auth-step__hint">
              Choose the role that matches your assignment. Senior supervisor and CSO roles require admin approval
              and cannot be self-assigned.
            </p>
            <RankSelector value={rank} onChange={setRank} />
            <div className="auth-actions">
              <button type="button" className="btn btn-ghost" onClick={goBack}>
                Back
              </button>
              <button type="button" className="btn btn-primary" onClick={goNext}>
                Continue
              </button>
            </div>
          </div>
        )}

        {step === 4 && isSecurityFlow && (
          <div className="auth-step">
            <h2 className="auth-step__title">Deployment</h2>
            <p className="subtle auth-step__hint">Where are you primarily deployed?</p>
            <div className="deploy-options">
              <label className={`deploy-card ${deployment === "ground" ? "deploy-card--selected" : ""}`}>
                <input
                  type="radio"
                  name="deploy"
                  checked={deployment === "ground"}
                  onChange={() => setDeployment("ground")}
                />
                <span className="deploy-card__title">Ground officer</span>
                <span className="deploy-card__desc">On patrol, site presence, and field response</span>
              </label>
              <label className={`deploy-card ${deployment === "command_centre" ? "deploy-card--selected" : ""}`}>
                <input
                  type="radio"
                  name="deploy"
                  checked={deployment === "command_centre"}
                  onChange={() => setDeployment("command_centre")}
                />
                <span className="deploy-card__title">Command centre (SCC / FCC)</span>
                <span className="deploy-card__desc">Monitoring, dispatch, and coordination</span>
              </label>
            </div>
            <div className="auth-actions">
              <button type="button" className="btn btn-ghost" onClick={goBack}>
                Back
              </button>
              <button type="button" className="btn btn-accent" disabled={loading} onClick={() => void submitSecurity()}>
                {loading ? "Creating account…" : "Create account"}
              </button>
            </div>
          </div>
        )}

        <p className="auth-footer subtle">
          Already have an account?{" "}
          <Link className="auth-link" to="/login">
            Sign in
          </Link>
        </p>
      </div>
    </div>
  );
}
