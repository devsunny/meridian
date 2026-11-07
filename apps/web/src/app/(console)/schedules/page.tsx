"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { CalendarClock, Clock3, Pause, Play, Plus, RefreshCw, Trash2 } from "lucide-react";
import { api, errorMessage } from "@/lib/api";
import { cronSummary, dateTime, relativeTime } from "@/lib/format";
import type { Ingestion, Pipeline, Schedule } from "@/lib/types";
import { Badge, Button, EmptyState, Field, InlineError, Modal, PageHeader, Spinner } from "@/components/ui";
import { useToast } from "@/components/ToastProvider";

export default function SchedulesPage() {
  const router = useRouter();
  const toast = useToast();
  const [schedules, setSchedules] = useState<Schedule[]>([]);
  const [pipelines, setPipelines] = useState<Pipeline[]>([]);
  const [ingestions, setIngestions] = useState<Ingestion[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [targetType, setTargetType] = useState("pipeline");
  const [targetId, setTargetId] = useState("");
  const [cron, setCron] = useState("0 6 * * *");
  const [timezone, setTimezone] = useState("America/New_York");
  const [saving, setSaving] = useState(false);

  async function load() {
    setLoading(true);
    setError("");
    try {
      const [scheduleRows, pipelineRows, ingestionRows] = await Promise.all([
        api.get<Schedule[]>("/schedules"),
        api.get<Pipeline[]>("/pipelines"),
        api.get<Ingestion[]>("/ingestions"),
      ]);
      setSchedules(scheduleRows);
      setPipelines(pipelineRows);
      setIngestions(ingestionRows);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  const names = useMemo(() => {
    const map: Record<string, string> = {};
    pipelines.forEach((item) => { map[item.id] = item.name; });
    ingestions.forEach((item) => { map[item.id] = item.name; });
    return map;
  }, [pipelines, ingestions]);

  const targets = targetType === "pipeline" ? pipelines : ingestions;

  function openCreate() {
    setTargetType("pipeline");
    setTargetId(pipelines[0]?.id || "");
    setName("");
    setCron("0 6 * * *");
    setTimezone("America/New_York");
    setOpen(true);
  }

  async function create(event: React.FormEvent) {
    event.preventDefault();
    setSaving(true);
    try {
      await api.post<Schedule>("/schedules", {
        name: name || `${names[targetId] || "Schedule"} schedule`,
        target_type: targetType,
        target_id: targetId,
        cron,
        timezone,
        enabled: true,
        max_concurrent_runs: 1,
      });
      setOpen(false);
      toast.push("Schedule armed. The scheduler will materialise it.", "success");
      await load();
    } catch (err) {
      toast.push(errorMessage(err), "error");
    } finally {
      setSaving(false);
    }
  }

  async function toggle(schedule: Schedule) {
    try {
      await api.patch(`/schedules/${schedule.id}`, { enabled: !schedule.enabled });
      await load();
    } catch (err) {
      toast.push(errorMessage(err), "error");
    }
  }

  async function runNow(schedule: Schedule) {
    try {
      const run = await api.post<{ id: string }>(`/schedules/${schedule.id}/run-now`);
      toast.push("Scheduled run materialised.", "success");
      router.push(`/runs/${run.id}`);
    } catch (err) {
      toast.push(errorMessage(err), "error");
    }
  }

  async function remove(schedule: Schedule) {
    if (!window.confirm(`Delete schedule “${schedule.name}”?`)) return;
    try {
      await api.delete(`/schedules/${schedule.id}`);
      toast.push("Schedule deleted.", "success");
      await load();
    } catch (err) {
      toast.push(errorMessage(err), "error");
    }
  }

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="Job scheduling"
        title="Schedules"
        description="Cron, timezone-aware schedules with concurrency limits. The scheduler writes exactly one run per logical date."
        actions={
          <>
            <Button variant="secondary" onClick={() => void load()}><RefreshCw size={15} /></Button>
            <Button variant="primary" onClick={openCreate}><Plus size={16} /> New schedule</Button>
          </>
        }
      />
      {error && <InlineError message={error} />}

      <div className="schedule-hero">
        <div><CalendarClock size={22} /><div><strong>{schedules.filter((item) => item.enabled).length} armed schedules</strong><span>Next materialisation: {schedules.find((item) => item.enabled && item.next_run_at)?.next_run_at ? relativeTime(schedules.find((item) => item.enabled && item.next_run_at)!.next_run_at) : "none"}</span></div></div>
        <div className="schedule-hero-r"><Clock3 size={16} /> scheduler poll 5s · Postgres SKIP LOCKED</div>
      </div>

      {loading ? <Spinner label="Loading schedules" /> : schedules.length === 0 ? (
        <EmptyState icon={<CalendarClock size={24} />} title="No schedules" description="Arm a pipeline or ingestion to run on a cron cadence." action={<Button variant="primary" onClick={openCreate}><Plus size={16} /> Create schedule</Button>} />
      ) : (
        <div className="table-card">
          <div className="table-wrap">
            <table className="data-table">
              <thead><tr><th>Schedule</th><th>Target</th><th>Cadence</th><th>Next run</th><th>Timezone</th><th>State</th><th /></tr></thead>
              <tbody>
                {schedules.map((schedule) => (
                  <tr key={schedule.id}>
                    <td><div className="cell-title">{schedule.name}</div><div className="cell-sub">{schedule.cron}</div></td>
                    <td><span className="type-tag">{schedule.target_type}</span><div className="cell-sub">{names[schedule.target_id] || schedule.target_id.slice(0, 18)}</div></td>
                    <td>{cronSummary(schedule.cron)}</td>
                    <td>{schedule.next_run_at ? <><div>{dateTime(schedule.next_run_at)}</div><div className="cell-sub">{relativeTime(schedule.next_run_at)}</div></> : "—"}</td>
                    <td className="muted">{schedule.timezone}</td>
                    <td><Badge tone={schedule.enabled ? "success" : "neutral"} dot>{schedule.enabled ? "armed" : "paused"}</Badge></td>
                    <td className="row-actions">
                      <Button size="sm" variant="ghost" onClick={() => void runNow(schedule)} title="Run now"><Play size={14} /></Button>
                      <Button size="sm" variant="ghost" onClick={() => void toggle(schedule)} title={schedule.enabled ? "Pause" : "Arm"}>{schedule.enabled ? <Pause size={14} /> : <Play size={14} />}</Button>
                      <Button size="sm" variant="ghost" onClick={() => void remove(schedule)} title="Delete"><Trash2 size={14} /></Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <Modal open={open} onClose={() => setOpen(false)} title="New schedule" subtitle="Schedules are evaluated in the selected IANA timezone and stored in UTC." width="md"
        footer={<><Button variant="ghost" onClick={() => setOpen(false)}>Cancel</Button><Button variant="primary" type="submit" form="schedule-form" disabled={saving}>{saving ? "Arming…" : "Arm schedule"}</Button></>}>
        <form id="schedule-form" onSubmit={create} className="form-grid">
          <Field label="Schedule name"><input value={name} onChange={(event) => setName(event.target.value)} placeholder="Customer Revenue Daily" /></Field>
          <div className="form-grid two">
            <Field label="Target type">
              <select value={targetType} onChange={(event) => { setTargetType(event.target.value); const list = event.target.value === "pipeline" ? pipelines : ingestions; setTargetId(list[0]?.id || ""); }}>
                <option value="pipeline">Pipeline</option><option value="ingestion">Ingestion</option>
              </select>
            </Field>
            <Field label="Target">
              <select value={targetId} onChange={(event) => setTargetId(event.target.value)}>
                {targets.map((target) => <option key={target.id} value={target.id}>{target.name}</option>)}
              </select>
            </Field>
          </div>
          <div className="form-grid two">
            <Field label="Cron expression" hint="Five fields: minute hour day month weekday." required>
              <input value={cron} onChange={(event) => setCron(event.target.value)} placeholder="0 6 * * *" />
            </Field>
            <Field label="Timezone">
              <select value={timezone} onChange={(event) => setTimezone(event.target.value)}>
                <option>America/New_York</option><option>UTC</option><option>Europe/London</option><option>Asia/Tokyo</option><option>Asia/Kolkata</option>
              </select>
            </Field>
          </div>
          <div className="review-box"><div><span>Preview</span><strong>{cronSummary(cron)} · {timezone}</strong></div><div><span>Concurrency</span><strong>1 active run</strong></div></div>
        </form>
      </Modal>
    </div>
  );
}
