import clsx from "clsx";
import { AlertTriangle, CalendarClock, CheckCircle2, CircleDashed, Clock, ExternalLink, Info, Plug, Star, XCircle, type LucideIcon } from "lucide-react";
import { Link } from "react-router-dom";
import { Badge, Card, CardHeader, Poster, RunStatusBadge, Spinner } from "../components/ui";
import { letterboxdUrl } from "../lib/api";
import { formatDate, formatDateTime, relativeTime, stars, summarize } from "../lib/format";
import { useSettings, useStatus } from "../lib/hooks";

function Stat({ label, value, icon: Icon, tone, to, hint }: { label: string; value: number; icon: LucideIcon; tone: string; to: string; hint?: string }) {
  return (
    <Link to={to} className="group">
      <Card className="p-4 transition-colors group-hover:border-zinc-700">
        <div className="flex items-center justify-between text-xs text-zinc-400">
          {label}
          <Icon className={clsx("size-4", tone)} />
        </div>
        <div className="mt-2 text-2xl font-semibold tabular-nums">{value.toLocaleString()}</div>
        <div className="mt-0.5 h-4 text-xs text-zinc-500">{hint}</div>
      </Card>
    </Link>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 py-2 text-sm">
      <span className="text-zinc-400">{label}</span>
      <span className="text-right text-zinc-200">{children}</span>
    </div>
  );
}

function Check({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      {ok ? <CheckCircle2 className="size-3.5 text-emerald-400" /> : <XCircle className="size-3.5 text-red-400" />}
      {label}
    </span>
  );
}

export function Dashboard() {
  const { data, isLoading } = useStatus();
  const { data: settings } = useSettings();
  if (isLoading || !data) return <Spinner />;
  const c = data.counts;
  const lastSync = data.last_sync;

  return (
    <div className="space-y-6">
      {!data.baseline_done && (
        <div className="flex gap-3 rounded-xl border border-sky-900/60 bg-sky-950/30 p-4 text-sm text-sky-200">
          <Info className="mt-0.5 size-4 shrink-0" />
          <div>
            <div className="font-medium">First sync will build the baseline</div>
            <div className="mt-1 text-sky-300/80">
              It reads your whole Letterboxd diary and marks Plex watches already logged there as synced. Unlogged watches older than{" "}
              {settings?.max_age_days ?? 30} days are skipped so old history doesn't flood the diary; you can queue them manually from Watches.
            </div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="Synced" value={c.synced} icon={CheckCircle2} tone="text-emerald-400" to="/watches?status=synced" hint={`${c.diary} diary entries known`} />
        <Stat
          label="Pending"
          value={c.pending}
          icon={CircleDashed}
          tone="text-sky-400"
          to="/watches?status=pending"
          hint={c.needs_rating ? `${c.needs_rating} waiting for a rating` : undefined}
        />
        <Stat label="Failed" value={c.failed} icon={AlertTriangle} tone="text-red-400" to="/watches?status=failed" />
        <Stat label="Skipped" value={c.skipped} icon={XCircle} tone="text-zinc-500" to="/watches?status=skipped" hint={`${c.movies} films tracked`} />
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader title="Recently logged" icon={<Star className="size-4 text-amber-400" />} action={<Link to="/watches?status=synced" className="text-xs text-zinc-400 hover:text-zinc-200">View all</Link>} />
          {data.recent_synced.length === 0 ? (
            <div className="px-4 py-10 text-center text-sm text-zinc-500">Nothing logged yet.</div>
          ) : (
            <div className="grid grid-cols-3 gap-4 p-4 sm:grid-cols-4 xl:grid-cols-6">
              {data.recent_synced.map((w) => {
                const href = letterboxdUrl(w);
                return (
                  <a key={w.id} href={href ?? undefined} target="_blank" rel="noreferrer" className="group min-w-0">
                    <Poster ratingKey={w.rating_key} hasPoster={w.has_poster} className="aspect-[2/3] w-full transition group-hover:ring-zinc-500" />
                    <div className="mt-1.5 truncate text-xs font-medium text-zinc-200" title={w.title}>{w.title}</div>
                    <div className="flex items-center justify-between text-[11px] text-zinc-500">
                      <span>{formatDate(w.watched_date)}</span>
                      <span className="text-emerald-400">{stars(w.rating10 ?? w.user_rating)}</span>
                    </div>
                  </a>
                );
              })}
            </div>
          )}
        </Card>

        <div className="space-y-6">
          <Card>
            <CardHeader title="Schedule" icon={<CalendarClock className="size-4 text-zinc-400" />} />
            <div className="divide-y divide-zinc-800/80 px-4">
              <Row label="Auto sync">
                {settings?.auto_sync ? `every ${settings.sync_interval_minutes >= 60 ? `${+(settings.sync_interval_minutes / 60).toFixed(1)}h` : `${settings.sync_interval_minutes}m`}` : <Badge tone="skipped">off</Badge>}
              </Row>
              <Row label="Next sync">
                <span title={formatDateTime(data.next_sync_at)}>{data.next_sync_at ? relativeTime(data.next_sync_at) : "—"}</span>
              </Row>
              <Row label="Last sync">
                {lastSync ? (
                  <Link to={`/runs/${lastSync.id}`} className="flex items-center gap-2 hover:underline">
                    <span title={formatDateTime(lastSync.started_at)}>{relativeTime(lastSync.started_at)}</span>
                    <RunStatusBadge run={lastSync} />
                  </Link>
                ) : (
                  "never"
                )}
              </Row>
              {lastSync && (lastSync.error || Object.keys(lastSync.summary).length > 0) && (
                <div className={clsx("py-2 text-xs", lastSync.error ? "text-red-400" : "text-zinc-400")}>{lastSync.error ?? summarize(lastSync.summary)}</div>
              )}
              <Row label="Diary last read">
                <span title={formatDateTime(data.diary_read_at)}>{relativeTime(data.diary_read_at)}</span>
              </Row>
            </div>
          </Card>

          <Card>
            <CardHeader title="Connections" icon={<Plug className="size-4 text-zinc-400" />} />
            <div className="divide-y divide-zinc-800/80 px-4">
              <Row label="Plex">
                <Check ok={data.config.plex_configured} label={data.config.plex_library} />
              </Row>
              <Row label="Letterboxd">
                <Check ok={data.config.letterboxd_configured} label={data.config.letterboxd_configured ? "credentials set" : "missing credentials"} />
              </Row>
              <Row label="Telegram">
                <Check ok={data.config.telegram_configured} label={data.config.telegram_configured ? (settings?.telegram_enabled ? "notifications on" : "muted") : "not configured"} />
              </Row>
              <Row label="Plex server">
                <a href={data.config.plex_url} target="_blank" rel="noreferrer" className="flex items-center gap-1 text-xs text-zinc-400 hover:text-zinc-200">
                  {data.config.plex_url.replace(/^https?:\/\//, "")}
                  <ExternalLink className="size-3" />
                </a>
              </Row>
            </div>
          </Card>

          {data.runner.queued.length > 0 && (
            <Card className="p-4 text-xs text-zinc-400">
              <Clock className="mb-1 inline size-3.5" /> Queued: {data.runner.queued.map((q) => q.kind).join(", ")}
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
