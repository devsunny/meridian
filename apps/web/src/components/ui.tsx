"use client";

import { X } from "lucide-react";
import { ReactNode, useEffect } from "react";

export function Button({
  children,
  variant = "secondary",
  size = "md",
  className = "",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger" | "dark";
  size?: "sm" | "md" | "lg";
}) {
  return (
    <button className={`btn btn-${variant} btn-${size} ${className}`} {...props}>
      {children}
    </button>
  );
}

export function Badge({
  children,
  tone = "neutral",
  dot = false,
}: {
  children: ReactNode;
  tone?: "success" | "danger" | "warning" | "info" | "neutral" | "violet";
  dot?: boolean;
}) {
  return (
    <span className={`badge badge-${tone}`}>
      {dot && <span className="badge-dot" />}
      {children}
    </span>
  );
}

export function StatusBadge({ status }: { status?: string | null }) {
  const value = (status || "unknown").toString();
  const normalized = value.toUpperCase();
  const tone =
    ["SUCCEEDED", "ACTIVE", "HEALTHY", "APPROVED", "CONFIGURED"].includes(normalized)
      ? "success"
      : ["FAILED", "CANCELLED", "DENIED", "UNREACHABLE", "ARCHIVED"].includes(normalized)
        ? "danger"
        : ["RUNNING", "QUEUED", "PENDING"].includes(normalized)
          ? "info"
          : normalized === "PAUSED"
            ? "warning"
            : "neutral";
  return (
    <Badge tone={tone} dot>
      {value.replace(/_/g, " ").toLowerCase()}
    </Badge>
  );
}

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="page-header">
      <div>
        {eyebrow && <div className="eyebrow">{eyebrow}</div>}
        <h1>{title}</h1>
        {description && <p className="page-description">{description}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </div>
  );
}

export function Modal({
  open,
  onClose,
  title,
  subtitle,
  children,
  footer,
  width = "md",
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  subtitle?: string;
  children: ReactNode;
  footer?: ReactNode;
  width?: "sm" | "md" | "lg" | "xl";
}) {
  useEffect(() => {
    if (!open) return;
    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.body.classList.add("modal-open");
    window.addEventListener("keydown", handler);
    return () => {
      document.body.classList.remove("modal-open");
      window.removeEventListener("keydown", handler);
    };
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <div className={`modal modal-${width}`} role="dialog" aria-modal="true" aria-label={title}>
        <div className="modal-head">
          <div>
            <h2>{title}</h2>
            {subtitle && <p>{subtitle}</p>}
          </div>
          <button className="icon-btn" onClick={onClose} aria-label="Close">
            <X size={18} />
          </button>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>
  );
}

export function Field({
  label,
  hint,
  required,
  children,
  htmlFor,
}: {
  label: string;
  hint?: string;
  required?: boolean;
  children: ReactNode;
  htmlFor?: string;
}) {
  return (
    <div className="field">
      <label htmlFor={htmlFor}>
        {label}
        {required && <span className="required">*</span>}
      </label>
      {children}
      {hint && <div className="field-hint">{hint}</div>}
    </div>
  );
}

export function EmptyState({
  icon,
  title,
  description,
  action,
}: {
  icon?: ReactNode;
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty-state">
      {icon && <div className="empty-icon">{icon}</div>}
      <h3>{title}</h3>
      {description && <p>{description}</p>}
      {action && <div className="empty-action">{action}</div>}
    </div>
  );
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <div className="loading">
      <span className="spinner" />
      <span>{label}</span>
    </div>
  );
}

export function InlineError({ message }: { message: string }) {
  return <div className="inline-error">{message}</div>;
}

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="kbd">{children}</kbd>;
}
