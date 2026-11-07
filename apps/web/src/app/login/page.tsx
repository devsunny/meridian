"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowRight, Database, Fingerprint, LockKeyhole, Network, ShieldCheck, Sparkles } from "lucide-react";
import { useAuth } from "@/components/AuthProvider";
import { Button } from "@/components/ui";
import { errorMessage } from "@/lib/api";

const DEMO_ACCOUNTS = [
  { email: "admin@meridian.local", label: "Platform admin", initials: "AC" },
  { email: "engineer@meridian.local", label: "Data engineer", initials: "NW" },
  { email: "analyst@meridian.local", label: "Business analyst", initials: "MA" },
  { email: "auditor@meridian.local", label: "Auditor", initials: "SO" },
];

function LoginForm() {
  const { login } = useAuth();
  const router = useRouter();
  const params = useSearchParams();
  const [email, setEmail] = useState("admin@meridian.local");
  const [password, setPassword] = useState("Meridian123!");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await login(email, password);
      router.replace(params.get("next") || "/");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-page">
      <section className="login-story">
        <div className="login-story-top">
          <div className="brand brand-light">
            <div className="brand-mark">
              <span />
              <span />
              <span />
              <span />
            </div>
            <div>
              <div className="brand-name">MERIDIAN</div>
              <div className="brand-sub">Data platform</div>
            </div>
          </div>
          <div className="login-badge"><span className="live-dot" /> self-hosted · v0.1</div>
        </div>

        <div className="login-copy">
          <div className="eyebrow light">Unified control plane</div>
          <h1>Operate enterprise data like a product.</h1>
          <p>
            Connect any source, land structured and unstructured data, orchestrate governed DAGs,
            and expose trusted context to BI and GenAI — from one console.
          </p>
          <div className="login-points">
            <div><Database size={17} /><span><strong>Any source.</strong> Databases, SFTP, S3, REST, Box, OneDrive, Google Drive and uploads.</span></div>
            <div><Network size={17} /><span><strong>Any workflow.</strong> Parallel DAGs, dependencies, retries, approvals and remote debugging.</span></div>
            <div><ShieldCheck size={17} /><span><strong>Governed by default.</strong> Tenant isolation, PII classification, expiring grants and audit chain.</span></div>
            <div><Sparkles size={17} /><span><strong>BI + GenAI ready.</strong> Catalog lineage and ACL-aware RAG with citations.</span></div>
          </div>
        </div>

        <div className="login-diagram" aria-hidden="true">
          <div className="diagram-node source"><span />Sources</div>
          <div className="diagram-line" />
          <div className="diagram-node core"><span />Control plane</div>
          <div className="diagram-line" />
          <div className="diagram-node lake"><span />Lakehouse</div>
          <div className="diagram-line" />
          <div className="diagram-node consume"><span />BI + AI</div>
        </div>

        <div className="login-story-foot">
          <span><LockKeyhole size={13} /> SOC 2 control mapping</span>
          <span><Fingerprint size={13} /> Request IDs end-to-end</span>
          <span><ShieldCheck size={13} /> Apache / MIT / BSD stack</span>
        </div>
      </section>

      <section className="login-panel">
        <div className="login-card">
          <div className="login-card-head">
            <div className="eyebrow">Welcome back</div>
            <h2>Sign in to Meridian</h2>
            <p>Use your enterprise identity or a local demo account.</p>
          </div>

          <Button variant="secondary" className="sso-button" type="button" onClick={() => setError("Configure OIDC in MERIDIAN_AUTH_MODE=oidc to enable enterprise SSO.")}>
            <Fingerprint size={18} /> Continue with enterprise SSO
          </Button>
          <div className="divider"><span>or use local credentials</span></div>

          <form onSubmit={submit} className="login-form">
            <label>
              Work email
              <input type="email" value={email} onChange={(event) => setEmail(event.target.value)} autoComplete="username" required />
            </label>
            <label>
              Password
              <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" required />
            </label>
            {error && <div className="inline-error">{error}</div>}
            <Button variant="primary" size="lg" type="submit" disabled={busy}>
              {busy ? "Signing in…" : "Sign in"} <ArrowRight size={17} />
            </Button>
          </form>

          <div className="demo-block">
            <div className="demo-head">Demo personas <span>password: Meridian123!</span></div>
            <div className="demo-grid">
              {DEMO_ACCOUNTS.map((account) => (
                <button
                  key={account.email}
                  type="button"
                  className={email === account.email ? "demo-account selected" : "demo-account"}
                  onClick={() => { setEmail(account.email); setPassword("Meridian123!"); }}
                >
                  <span className="demo-avatar">{account.initials}</span>
                  <span><strong>{account.label}</strong><small>{account.email}</small></span>
                </button>
              ))}
            </div>
          </div>
          <p className="login-legal">Protected by tenant-scoped RBAC. Every sign-in and data access is written to the audit chain.</p>
        </div>
      </section>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={<div className="app-loading">Loading sign-in…</div>}>
      <LoginForm />
    </Suspense>
  );
}
