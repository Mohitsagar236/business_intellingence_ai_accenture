import { useState } from "react";
import type { FormEvent } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import type { Location } from "react-router-dom";
import { BarChart3, Building2, Eye, Lock, ShieldCheck, Sparkles, User } from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import "./Login.css";

const DEMO_ACCOUNTS = [
  { username: "analyst", password: "analyst123", label: "Analyst", icon: BarChart3 },
  { username: "depthead", password: "depthead123", label: "Dept. Head", icon: Building2 },
  { username: "admin", password: "admin123", label: "Admin", icon: ShieldCheck },
  { username: "exec", password: "exec123", label: "Executive", icon: Eye },
];

const VALUE_PROPS = [
  "A cause is only validated when structured and unstructured evidence actually agree.",
  "Every claim in a report cites the evidence behind it — nothing ungrounded survives.",
  "Genuine ambiguity is reported honestly, ranked, with what would resolve it.",
];

export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: Location } | null)?.from?.pathname ?? "/";

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setIsSubmitting(true);
    try {
      await login(username, password);
      navigate(from, { replace: true });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setIsSubmitting(false);
    }
  }

  function fillDemo(u: string, p: string) {
    setUsername(u);
    setPassword(p);
  }

  return (
    <div className="login-page">
      <div className="login-brand-panel">
        <div className="login-brand-inner">
          <div className="brand login-brand">
            <span className="brand-mark">›</span>
            <span className="brand-name">BusinessIntelligence.ai</span>
          </div>
          <h1 className="login-tagline">From "what changed" to "why" — grounded, not guessed.</h1>
          <ul className="login-value-props">
            {VALUE_PROPS.map((text) => (
              <li key={text}>
                <Sparkles size={15} strokeWidth={2.25} aria-hidden="true" />
                <span>{text}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>

      <div className="login-form-panel">
        <div className="login-card">
          <div className="login-card-head">
            <h2>Sign in</h2>
            <p className="login-sub">View KPI diagnoses and the evidence behind them.</p>
          </div>

          <form onSubmit={handleSubmit} className="login-form">
            <label>
              Username
              <div className="input-with-icon">
                <User size={15} strokeWidth={2.25} aria-hidden="true" />
                <input value={username} onChange={(e) => setUsername(e.target.value)} autoFocus autoComplete="username" />
              </div>
            </label>
            <label>
              Password
              <div className="input-with-icon">
                <Lock size={15} strokeWidth={2.25} aria-hidden="true" />
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="current-password"
                />
              </div>
            </label>
            {error && <div className="login-error">{error}</div>}
            <button type="submit" className="btn-run login-submit" disabled={isSubmitting}>
              {isSubmitting ? "Signing in…" : "Sign in"}
            </button>
          </form>

          <div className="demo-accounts">
            <span className="demo-label">Demo accounts — SRS §2.3 user classes</span>
            <div className="demo-grid">
              {DEMO_ACCOUNTS.map((a) => (
                <button key={a.username} type="button" className="btn-secondary" onClick={() => fillDemo(a.username, a.password)}>
                  <a.icon size={13} strokeWidth={2.25} aria-hidden="true" />
                  {a.label}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
