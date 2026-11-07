"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import {
  ArrowDownToLine,
  BookOpen,
  CalendarClock,
  ChevronRight,
  Database,
  KeyRound,
  LayoutDashboard,
  LogOut,
  Menu,
  PlayCircle,
  Plug,
  Search,
  Settings,
  ShieldCheck,
  Sparkles,
  TerminalSquare,
  Workflow,
  X,
} from "lucide-react";
import { useAuth } from "./AuthProvider";
import { Spinner } from "./ui";

const NAV = [
  {
    section: "Workspace",
    items: [
      { href: "/", label: "Overview", icon: LayoutDashboard, permission: null },
      { href: "/sources", label: "Sources", icon: Database, permission: "sources:read" },
      { href: "/ingestions", label: "Ingestion", icon: ArrowDownToLine, permission: "ingestions:read" },
      { href: "/pipelines", label: "Pipelines", icon: Workflow, permission: "pipelines:read" },
      { href: "/runs", label: "Runs & debug", icon: PlayCircle, permission: "runs:read" },
      { href: "/schedules", label: "Schedules", icon: CalendarClock, permission: "schedules:read" },
      { href: "/assistant", label: "Ask Meridian", icon: Sparkles, permission: "assist:use" },
    ],
  },
  {
    section: "Govern",
    items: [
      { href: "/catalog", label: "Data catalog", icon: BookOpen, permission: "catalog:read" },
      { href: "/governance", label: "Governance", icon: ShieldCheck, permission: "governance:read" },
      { href: "/security", label: "Security", icon: KeyRound, permission: "security:read" },
      { href: "/integrations", label: "Integrations", icon: Plug, permission: "integrations:read" },
    ],
  },
  {
    section: "Operate",
    items: [
      { href: "/terminal", label: "Remote terminal", icon: TerminalSquare, permission: null },
      { href: "/settings", label: "Platform", icon: Settings, permission: null },
    ],
  },
];

const TITLES: Record<string, string> = {
  "/": "Overview",
  "/sources": "Sources",
  "/ingestions": "Ingestion",
  "/pipelines": "Pipelines",
  "/runs": "Runs & debugging",
  "/schedules": "Schedules",
  "/assistant": "Ask Meridian",
  "/catalog": "Data catalog",
  "/governance": "Governance",
  "/security": "Security",
  "/integrations": "Integrations",
  "/terminal": "Remote terminal",
  "/settings": "Platform",
};

export function RequireAuth({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const pathname = usePathname();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !user) {
      router.replace(`/login?next=${encodeURIComponent(pathname)}`);
    }
  }, [loading, user, router, pathname]);

  if (loading || !user) {
    return (
      <div className="app-loading">
        <div className="brand-mark large">
          <span />
          <span />
          <span />
          <span />
        </div>
        <Spinner label="Opening workspace" />
      </div>
    );
  }
  return <>{children}</>;
}

function Logo() {
  return (
    <div className="brand">
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
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { user, logout } = useAuth();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [query, setQuery] = useState("");

  useEffect(() => {
    setMobileOpen(false);
  }, [pathname]);

  const section = pathname === "/" ? "Overview" : TITLES[Object.keys(TITLES).find((key) => key !== "/" && pathname.startsWith(key)) || "/"] || "Workspace";
  const initials = (user?.name || "M")
    .split(" ")
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
  const permissions = user?.permissions || [];
  const can = (permission: string | null) => !permission || permissions.includes("*") || permissions.includes(permission);

  return (
    <div className="app-shell">
      {mobileOpen && <div className="sidebar-scrim" onClick={() => setMobileOpen(false)} />}
      <aside className={`sidebar ${mobileOpen ? "open" : ""}`}>
        <div className="sidebar-head">
          <Logo />
          <button className="icon-btn sidebar-close" onClick={() => setMobileOpen(false)} aria-label="Close navigation">
            <X size={18} />
          </button>
        </div>
        <nav className="sidebar-nav">
          {NAV.map((group) => {
            const items = group.items.filter((item) => can(item.permission));
            if (!items.length) return null;
            return (
              <div className="nav-group" key={group.section}>
                <div className="nav-label">{group.section}</div>
                {items.map((item) => {
                  const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
                  const Icon = item.icon;
                  return (
                    <Link key={item.href} href={item.href} className={`nav-item ${active ? "active" : ""}`}>
                      <Icon size={17} strokeWidth={1.8} />
                      <span>{item.label}</span>
                      {active && <ChevronRight size={13} className="nav-arrow" />}
                    </Link>
                  );
                })}
              </div>
            );
          })}
        </nav>
        <div className="sidebar-foot">
          <div className="trust-card">
            <div className="trust-title">
              <ShieldCheck size={15} /> Governed by default
            </div>
            <p>Tenant isolation, audit chain and PII classification are enforced server-side.</p>
            <div className="trust-tags">
              <span>SOC 2</span>
              <span>OTel</span>
              <span>JSONL</span>
            </div>
          </div>
          <div className="tenant-switcher">
            <div className="tenant-avatar">{initials}</div>
            <div>
              <strong>{user?.tenant_slug}</strong>
              <small>{user?.role_label || user?.role}</small>
            </div>
          </div>
        </div>
      </aside>

      <div className="main-shell">
        <header className="topbar">
          <div className="topbar-left">
            <button className="icon-btn mobile-menu" onClick={() => setMobileOpen(true)} aria-label="Open navigation">
              <Menu size={19} />
            </button>
            <div className="crumb">
              <span>Acme Analytics</span>
              <ChevronRight size={13} />
              <strong>{section}</strong>
            </div>
          </div>
          <div className="topbar-right">
            <form
              className="top-search"
              onSubmit={(event) => {
                event.preventDefault();
                if (query.trim()) router.push(`/catalog?q=${encodeURIComponent(query.trim())}`);
              }}
            >
              <Search size={15} />
              <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search governed data…" aria-label="Search catalog" />
              <kbd>↵</kbd>
            </form>
            <div className="env-pill"><span className="live-dot" /> local</div>
            <div className="user-menu">
              <div className="avatar">{initials}</div>
              <div className="user-meta">
                <strong>{user?.name}</strong>
                <small>{user?.email}</small>
              </div>
              <button className="icon-btn" aria-label="Sign out" title="Sign out" onClick={() => void logout()}>
                <LogOut size={16} />
              </button>
            </div>
          </div>
        </header>
        <main className="content">{children}</main>
      </div>
    </div>
  );
}
