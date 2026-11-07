"use client";

import { useEffect, useState } from "react";
import { Check, Copy, KeyRound, Lock, Plus, RefreshCw, Shield, Trash2, UserCog, Users } from "lucide-react";
import { api, errorMessage } from "@/lib/api";
import { dateTime, relativeTime } from "@/lib/format";
import type { ApiKey, PlatformUser, Role } from "@/lib/types";
import { Badge, Button, EmptyState, Field, InlineError, Modal, PageHeader, Spinner } from "@/components/ui";
import { useAuth } from "@/components/AuthProvider";
import { useToast } from "@/components/ToastProvider";

type Tab = "users" | "roles" | "keys";

interface RoleInfo {
  name: Role;
  label: string;
  permissions: string[];
}

export default function SecurityPage() {
  const { user } = useAuth();
  const toast = useToast();
  const [tab, setTab] = useState<Tab>("users");
  const [users, setUsers] = useState<PlatformUser[]>([]);
  const [roles, setRoles] = useState<RoleInfo[]>([]);
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [overview, setOverview] = useState<{ users: number; active_users: number; admins: number; active_api_keys: number; auth_mode: string } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [userOpen, setUserOpen] = useState(false);
  const [keyOpen, setKeyOpen] = useState(false);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("analyst");
  const [password, setPassword] = useState("");
  const [keyName, setKeyName] = useState("");
  const [newKey, setNewKey] = useState<string | null>(null);
  const [temporary, setTemporary] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function load() {
    setLoading(true);
    setError("");
    try {
      const [userRows, roleData, keyRows, overviewData] = await Promise.all([
        api.get<PlatformUser[]>("/security/users"),
        api.get<{ roles: RoleInfo[] }>("/security/roles"),
        api.get<ApiKey[]>("/security/api-keys"),
        api.get<any>("/security/overview"),
      ]);
      setUsers(userRows);
      setRoles(roleData.roles);
      setKeys(keyRows);
      setOverview(overviewData);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function createUser(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      const result = await api.post<{ temporary_password: string | null }>("/security/users", { name, email, role, password: password || null });
      setUserOpen(false);
      setTemporary(result.temporary_password);
      toast.push("User provisioned.", "success");
      await load();
    } catch (err) {
      toast.push(errorMessage(err), "error");
    } finally {
      setBusy(false);
    }
  }

  async function updateRole(target: PlatformUser, newRole: Role) {
    try {
      await api.patch(`/security/users/${target.id}`, { role: newRole });
      toast.push("Role updated.", "success");
      await load();
    } catch (err) {
      toast.push(errorMessage(err), "error");
    }
  }

  async function toggleUser(target: PlatformUser) {
    try {
      await api.patch(`/security/users/${target.id}`, { is_active: !target.is_active });
      await load();
    } catch (err) {
      toast.push(errorMessage(err), "error");
    }
  }

  async function createKey(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      const result = await api.post<{ key: string }>("/security/api-keys", { name: keyName, expires_days: 90 });
      setKeyOpen(false);
      setNewKey(result.key);
      await load();
    } catch (err) {
      toast.push(errorMessage(err), "error");
    } finally {
      setBusy(false);
    }
  }

  async function revokeKey(id: string) {
    try {
      await api.delete(`/security/api-keys/${id}`);
      toast.push("API key revoked.", "success");
      await load();
    } catch (err) {
      toast.push(errorMessage(err), "error");
    }
  }

  if (loading) return <Spinner label="Loading security" />;
  if (error) return <InlineError message={error} />;

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="Identity & access"
        title="Security"
        description="Role-based access, scoped API keys and tenant isolation. The UI hides what you cannot use; the API enforces it."
        actions={<Button variant="secondary" onClick={() => void load()}><RefreshCw size={15} /> Refresh</Button>}
      />

      <div className="security-hero">
        <div className="security-shield"><Shield size={26} /></div>
        <div><strong>{overview?.auth_mode === "oidc" ? "Enterprise SSO enforced" : "Local identity (demo)"}</strong><span>{overview?.active_users} active users · {overview?.admins} administrators · {overview?.active_api_keys} active API keys</span></div>
        <div className="security-pills"><span><Lock size={13} /> tenant scoped</span><span><KeyRound size={13} /> expiring keys</span><span><UserCog size={13} /> six roles</span></div>
      </div>

      <div className="tabs">
        <button className={`tab ${tab === "users" ? "active" : ""}`} onClick={() => setTab("users")}><Users size={14} /> Users</button>
        <button className={`tab ${tab === "roles" ? "active" : ""}`} onClick={() => setTab("roles")}><Shield size={14} /> Roles</button>
        <button className={`tab ${tab === "keys" ? "active" : ""}`} onClick={() => setTab("keys")}><KeyRound size={14} /> API keys</button>
      </div>

      {tab === "users" && (
        <section className="panel">
          <div className="panel-head"><div><h2>Tenant users</h2><p>Provision people from your IdP or create local demo accounts.</p></div><Button size="sm" variant="primary" onClick={() => { setName(""); setEmail(""); setRole("analyst"); setPassword(""); setUserOpen(true); }}><Plus size={14} /> Add user</Button></div>
          <div className="table-wrap">
            <table className="data-table">
              <thead><tr><th>User</th><th>Role</th><th>Status</th><th>Last sign-in</th><th /></tr></thead>
              <tbody>
                {users.map((item) => (
                  <tr key={item.id}>
                    <td><div className="user-cell"><div className="avatar small">{item.name.split(" ").map((part) => part[0]).join("").slice(0, 2)}</div><div><div className="cell-title">{item.name}</div><div className="cell-sub">{item.email}</div></div></div></td>
                    <td>
                      <select value={item.role} onChange={(event) => void updateRole(item, event.target.value as Role)} disabled={item.id === user?.id}>
                        {roles.map((roleInfo) => <option key={roleInfo.name} value={roleInfo.name}>{roleInfo.label}</option>)}
                      </select>
                    </td>
                    <td><Badge tone={item.is_active ? "success" : "neutral"} dot>{item.is_active ? "active" : "disabled"}</Badge></td>
                    <td className="muted">{item.last_login_at ? relativeTime(item.last_login_at) : "never"}</td>
                    <td><Button size="sm" variant="ghost" onClick={() => void toggleUser(item)} disabled={item.id === user?.id}>{item.is_active ? "Disable" : "Enable"}</Button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {tab === "roles" && (
        <div className="role-grid">
          {roles.map((roleInfo) => (
            <div className="role-card" key={roleInfo.name}>
              <div className="role-card-head"><div className="role-icon"><Shield size={17} /></div><div><strong>{roleInfo.label}</strong><code>{roleInfo.name}</code></div>{user?.role === roleInfo.name && <Badge tone="violet">your role</Badge>}</div>
              <div className="permission-list">
                {roleInfo.permissions.map((permission) => <span key={permission}><Check size={12} /> {permission === "*" ? "All permissions" : permission}</span>)}
              </div>
            </div>
          ))}
        </div>
      )}

      {tab === "keys" && (
        <section className="panel">
          <div className="panel-head"><div><h2>API keys</h2><p>Machine credentials for the CLI and automation. Keys are hashed at rest and shown once.</p></div><Button size="sm" variant="primary" onClick={() => { setKeyName(""); setKeyOpen(true); }}><Plus size={14} /> Issue key</Button></div>
          {keys.length ? (
            <div className="table-wrap">
              <table className="data-table">
                <thead><tr><th>Name</th><th>Prefix</th><th>Created</th><th>Expires</th><th>Last used</th><th>Status</th><th /></tr></thead>
                <tbody>
                  {keys.map((key) => (
                    <tr key={key.id}>
                      <td className="cell-title">{key.name}</td>
                      <td><code>{key.prefix}…</code></td>
                      <td className="muted">{dateTime(key.created_at)}</td>
                      <td className="muted">{dateTime(key.expires_at)}</td>
                      <td className="muted">{key.last_used_at ? relativeTime(key.last_used_at) : "never"}</td>
                      <td><Badge tone={key.revoked_at ? "danger" : "success"} dot>{key.revoked_at ? "revoked" : "active"}</Badge></td>
                      <td>{!key.revoked_at && <Button size="sm" variant="ghost" onClick={() => void revokeKey(key.id)}><Trash2 size={14} /></Button>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <EmptyState icon={<KeyRound size={22} />} title="No API keys" description="Issue a key for the CLI or a service account." />}
        </section>
      )}

      <Modal open={userOpen} onClose={() => setUserOpen(false)} title="Add tenant user" subtitle="The user is scoped to this tenant. Leave password blank to generate a temporary credential." width="md"
        footer={<><Button variant="ghost" onClick={() => setUserOpen(false)}>Cancel</Button><Button variant="primary" type="submit" form="user-form" disabled={busy}>{busy ? "Provisioning…" : "Create user"}</Button></>}>
        <form id="user-form" onSubmit={createUser} className="form-grid">
          <Field label="Full name" required><input value={name} onChange={(event) => setName(event.target.value)} required /></Field>
          <Field label="Work email" required><input type="email" value={email} onChange={(event) => setEmail(event.target.value)} required /></Field>
          <Field label="Role"><select value={role} onChange={(event) => setRole(event.target.value as Role)}>{roles.map((roleInfo) => <option key={roleInfo.name} value={roleInfo.name}>{roleInfo.label}</option>)}</select></Field>
          <Field label="Temporary password" hint="Optional. Minimum 10 characters."><input type="password" value={password} onChange={(event) => setPassword(event.target.value)} minLength={password ? 10 : undefined} /></Field>
        </form>
      </Modal>

      <Modal open={keyOpen} onClose={() => setKeyOpen(false)} title="Issue API key" subtitle="The key inherits your role and tenant. Store it in a secret manager." width="md"
        footer={<><Button variant="ghost" onClick={() => setKeyOpen(false)}>Cancel</Button><Button variant="primary" type="submit" form="key-form" disabled={busy}>{busy ? "Issuing…" : "Issue key"}</Button></>}>
        <form id="key-form" onSubmit={createKey} className="form-grid">
          <Field label="Key name" required><input value={keyName} onChange={(event) => setKeyName(event.target.value)} placeholder="ci-deploy" required /></Field>
          <div className="review-box"><div><span>Expiry</span><strong>90 days</strong></div><div><span>Scope</span><strong>{user?.role}</strong></div></div>
        </form>
      </Modal>

      <Modal open={!!newKey} onClose={() => setNewKey(null)} title="Copy your API key" subtitle="This value is shown once and never stored in plaintext." width="md"
        footer={<Button variant="primary" onClick={() => setNewKey(null)}>I have stored it</Button>}>
        <div className="secret-reveal"><code>{newKey}</code><Button variant="secondary" onClick={() => { if (newKey) { void navigator.clipboard.writeText(newKey); toast.push("Key copied", "success"); } }}><Copy size={15} /> Copy</Button></div>
        <p className="muted">Use it as <code>Authorization: Bearer mk_…</code> with the API or <code>meridian --token</code> with the CLI.</p>
      </Modal>

      <Modal open={!!temporary} onClose={() => setTemporary(null)} title="Temporary password" subtitle="Share over a secure channel and require a change at first sign-in." width="md"
        footer={<Button variant="primary" onClick={() => setTemporary(null)}>Done</Button>}>
        <div className="secret-reveal"><code>{temporary}</code><Button variant="secondary" onClick={() => { if (temporary) { void navigator.clipboard.writeText(temporary); toast.push("Password copied", "success"); } }}><Copy size={15} /> Copy</Button></div>
      </Modal>
    </div>
  );
}
