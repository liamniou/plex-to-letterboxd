import { useMutation, useQueryClient } from "@tanstack/react-query";
import { BookOpenCheck, Copy, ScanSearch, Webhook } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { Button, Card, CardHeader, Spinner, Toggle } from "../components/ui";
import { api, type Settings as SettingsT } from "../lib/api";
import { useBusy, useSettings, useStartJob } from "../lib/hooks";

function Field({ label, hint, children }: { label: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-2 py-4 sm:flex-row sm:items-center sm:justify-between sm:gap-8">
      <div className="min-w-0">
        <div className="text-sm font-medium text-zinc-200">{label}</div>
        {hint && <div className="mt-0.5 text-xs text-zinc-500">{hint}</div>}
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  );
}

const inputCls = "h-9 rounded-md border border-zinc-800 bg-zinc-950 px-3 text-sm outline-none focus:border-zinc-600";

export function Settings() {
  const { data } = useSettings();
  const [form, setForm] = useState<SettingsT | null>(null);
  const qc = useQueryClient();
  const { busy } = useBusy();
  const startJob = useStartJob();
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (data) setForm(data);
  }, [data]);

  const save = useMutation({
    mutationFn: api.saveSettings,
    onSuccess: (s) => {
      qc.setQueryData(["settings"], s);
      qc.invalidateQueries({ queryKey: ["status"] });
    },
  });

  if (!form || !data) return <Spinner />;
  const dirty = JSON.stringify(form) !== JSON.stringify(data);
  const set = <K extends keyof SettingsT>(k: K, v: SettingsT[K]) => setForm({ ...form, [k]: v });
  const num = (k: keyof SettingsT, min = 0) => (
    <input type="number" min={min} className={`${inputCls} w-28 text-right tabular-nums`} value={form[k] as number} onChange={(e) => set(k, Number(e.target.value) as never)} />
  );
  const webhookUrl = `${window.location.origin}/api/webhook/tautulli`;

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <Card>
        <CardHeader title="Sync" />
        <div className="divide-y divide-zinc-800/80 px-4">
          <Field label="Automatic sync" hint="Scan Plex and log new watches on a schedule.">
            <Toggle checked={form.auto_sync} onChange={(v) => set("auto_sync", v)} label="Automatic sync" />
          </Field>
          <Field label="Interval (minutes)" hint="How often the scheduled sync runs.">
            {num("sync_interval_minutes", 5)}
          </Field>
          <Field label="Require a rating" hint="Hold watches until you rate the film in Plex, so no unrated diary entries are created.">
            <Toggle checked={form.require_rating} onChange={(v) => set("require_rating", v)} label="Require a rating" />
          </Field>
          <Field label="Max age (days)" hint="Newly discovered watches older than this are skipped instead of queued (e.g. bulk 'mark as watched'). 0 = no limit.">
            {num("max_age_days")}
          </Field>
          <Field label="Max attempts" hint="Automatic retries for a watch before it stays failed.">
            {num("max_attempts", 1)}
          </Field>
          <Field label="Batch size" hint="Maximum films per Letterboxd import.">
            {num("batch_size", 1)}
          </Field>
        </div>
      </Card>

      <Card>
        <CardHeader title="Plex" />
        <div className="divide-y divide-zinc-800/80 px-4">
          <Field label="Library" hint="Name of the movie library to read.">
            <input className={`${inputCls} w-48`} value={form.plex_library} onChange={(e) => set("plex_library", e.target.value)} />
          </Field>
          <Field label="Plex user" hint="Managed/home user whose watches and ratings to use. Empty = server owner.">
            <input className={`${inputCls} w-48`} value={form.plex_user} placeholder="owner" onChange={(e) => set("plex_user", e.target.value)} />
          </Field>
          <Field label="History window (days)" hint="Also read per-play history this far back, so several plays between syncs are all captured.">
            {num("history_days")}
          </Field>
        </div>
      </Card>

      <Card>
        <CardHeader title="Notifications" />
        <div className="px-4">
          <Field label="Telegram" hint="Message after each sync that logs films, and on failures (needs TELEGRAM_* env vars).">
            <Toggle checked={form.telegram_enabled} onChange={(v) => set("telegram_enabled", v)} label="Telegram" />
          </Field>
        </div>
      </Card>

      <div className="flex items-center justify-end gap-3">
        {save.isError && <span className="text-sm text-red-400">{(save.error as Error).message}</span>}
        {save.isSuccess && !dirty && <span className="text-sm text-emerald-400">Saved</span>}
        <Button variant="ghost" disabled={!dirty} onClick={() => setForm(data)}>
          Reset
        </Button>
        <Button variant="primary" disabled={!dirty} loading={save.isPending} onClick={() => save.mutate(form)}>
          Save changes
        </Button>
      </div>

      <Card>
        <CardHeader title="Maintenance" />
        <div className="divide-y divide-zinc-800/80 px-4">
          <Field label="Scan Plex" hint="Read watches and ratings from Plex without touching Letterboxd.">
            <Button onClick={() => startJob.mutate("scan")} disabled={busy}>
              <ScanSearch className="size-4" /> Scan
            </Button>
          </Field>
          <Field label="Reconcile with diary" hint="Read the full Letterboxd diary and mark pending/failed watches that are already logged as synced.">
            <Button onClick={() => startJob.mutate("reconcile")} disabled={busy}>
              <BookOpenCheck className="size-4" /> Reconcile
            </Button>
          </Field>
          <Field
            label="Tautulli webhook"
            hint={
              <>
                Optional: add a Webhook notification agent (POST, JSON) on <em>Watched</em> to trigger a sync immediately.
              </>
            }
          >
            <Button
              variant="ghost"
              onClick={() => {
                navigator.clipboard?.writeText(webhookUrl);
                setCopied(true);
                setTimeout(() => setCopied(false), 1500);
              }}
            >
              <Webhook className="size-4" />
              <code className="text-xs">{webhookUrl}</code>
              <Copy className="size-3.5" />
              {copied && <span className="text-xs text-emerald-400">copied</span>}
            </Button>
          </Field>
        </div>
      </Card>
    </div>
  );
}
