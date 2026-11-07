export function bytes(value?: number | null): string {
  if (!value) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = value;
  let index = 0;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  return `${size.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

export function number(value?: number | null): string {
  return new Intl.NumberFormat("en-US").format(value || 0);
}

export function dateTime(value?: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

export function relativeTime(value?: string | null): string {
  if (!value) return "—";
  const then = new Date(value).getTime();
  if (Number.isNaN(then)) return value;
  const delta = Math.round((then - Date.now()) / 1000);
  const abs = Math.abs(delta);
  const formatter = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
  if (abs < 60) return formatter.format(delta, "second");
  if (abs < 3600) return formatter.format(Math.round(delta / 60), "minute");
  if (abs < 86400) return formatter.format(Math.round(delta / 3600), "hour");
  return formatter.format(Math.round(delta / 86400), "day");
}

export function duration(start?: string | null, end?: string | null): string {
  if (!start) return "—";
  const startTime = new Date(start).getTime();
  const endTime = end ? new Date(end).getTime() : Date.now();
  const seconds = Math.max(0, Math.round((endTime - startTime) / 1000));
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
}

export function statusTone(status?: string | null): "success" | "danger" | "warning" | "info" | "neutral" {
  switch ((status || "").toUpperCase()) {
    case "SUCCEEDED":
    case "ACTIVE":
    case "HEALTHY":
    case "APPROVED":
    case "CONFIGURED":
      return "success";
    case "FAILED":
    case "CANCELLED":
    case "DENIED":
    case "UNREACHABLE":
    case "ARCHIVED":
      return "danger";
    case "RUNNING":
    case "QUEUED":
    case "PENDING":
      return "info";
    case "PAUSED":
      return "warning";
    default:
      return "neutral";
  }
}

export function classificationTone(value?: string | null): "success" | "danger" | "warning" | "info" | "neutral" {
  switch (value) {
    case "public":
      return "success";
    case "internal":
      return "info";
    case "confidential":
      return "warning";
    case "restricted":
      return "danger";
    default:
      return "neutral";
  }
}

export function titleCase(value?: string | null): string {
  if (!value) return "";
  return value
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

export function cronSummary(cron: string): string {
  const parts = cron.trim().split(/\s+/);
  if (parts.length !== 5) return cron;
  const [minute, hour, day, month, weekday] = parts;
  if (minute === "0" && hour !== "*" && day === "*" && month === "*" && weekday === "*") {
    return `Daily at ${hour.padStart(2, "0")}:00`;
  }
  if (minute !== "*" && hour !== "*" && day === "*" && month === "*" && weekday !== "*") {
    return `Weekly (${weekday}) at ${hour.padStart(2, "0")}:${minute.padStart(2, "0")}`;
  }
  return cron;
}
