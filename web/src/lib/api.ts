export type WatchStatus = "pending" | "synced" | "failed" | "skipped";

export interface Watch {
  id: number;
  rating_key: number;
  watched_date: string;
  watched_at: string | null;
  source: string;
  status: WatchStatus;
  rewatch: number;
  rating10: number | null;
  attempts: number;
  last_error: string | null;
  note: string | null;
  synced_at: string | null;
  lb_viewing_id: string | null;
  title: string;
  year: number | null;
  imdb_id: string | null;
  tmdb_id: string | null;
  user_rating: number | null;
  view_count: number;
  lb_slug: string | null;
  has_poster: number;
}

export interface Run {
  id: number;
  kind: "scan" | "sync" | "reconcile";
  trigger: string;
  status: "running" | "success" | "failed";
  started_at: string;
  finished_at: string | null;
  summary: Record<string, unknown>;
  error: string | null;
}

export interface LogLine {
  id: number;
  ts: string;
  level: string;
  message: string;
}

export interface Job {
  kind: string;
  trigger: string;
  run_id?: number;
  started_at?: string;
  queued_at?: string;
}

export interface Status {
  version: string;
  runner: { current: Job | null; queued: Job[] };
  next_sync_at: string | null;
  baseline_done: boolean;
  baseline_at: string | null;
  diary_read_at: string | null;
  counts: Record<WatchStatus | "needs_rating" | "movies" | "diary", number>;
  last_sync: Run | null;
  recent_synced: Watch[];
  config: {
    plex_url: string;
    plex_machine_id: string | null;
    plex_library: string;
    plex_configured: boolean;
    letterboxd_configured: boolean;
    telegram_configured: boolean;
  };
}

export interface Settings {
  auto_sync: boolean;
  sync_interval_minutes: number;
  plex_library: string;
  plex_user: string;
  require_rating: boolean;
  history_days: number;
  max_age_days: number;
  max_attempts: number;
  batch_size: number;
  telegram_enabled: boolean;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export type WatchAction = "queue" | "skip" | "mark_synced";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { ...init, headers: { "Content-Type": "application/json", ...init?.headers } });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(typeof body.detail === "string" ? body.detail : res.statusText);
  }
  return res.json();
}

export const api = {
  status: () => req<Status>("/api/status"),
  watches: (params: { status?: string; q?: string; needs_rating?: boolean; page: number; page_size: number }) => {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => v !== undefined && v !== "" && qs.set(k, String(v)));
    return req<Page<Watch>>(`/api/watches?${qs}`);
  },
  watchAction: (ids: number[], action: WatchAction) =>
    req<{ updated: number }>("/api/watches/action", { method: "POST", body: JSON.stringify({ ids, action }) }),
  startJob: (kind: "scan" | "sync" | "reconcile") => req<{ enqueued: boolean }>(`/api/jobs/${kind}`, { method: "POST" }),
  runs: (limit = 100) => req<{ items: Run[] }>(`/api/runs?limit=${limit}`),
  run: (id: number, afterId = 0) => req<{ run: Run; logs: LogLine[] }>(`/api/runs/${id}?after_id=${afterId}`),
  settings: () => req<Settings>("/api/settings"),
  saveSettings: (s: Partial<Settings>) => req<Settings>("/api/settings", { method: "PUT", body: JSON.stringify(s) }),
};

export const posterUrl = (ratingKey: number) => `/api/poster/${ratingKey}`;
export const plexUrl = (machineId: string | null | undefined, ratingKey: number) =>
  machineId
    ? `https://app.plex.tv/desktop/#!/server/${machineId}/details?key=${encodeURIComponent(`/library/metadata/${ratingKey}`)}`
    : null;

export const letterboxdUrl = (w: Pick<Watch, "lb_slug" | "tmdb_id" | "imdb_id">) =>
  w.lb_slug
    ? `https://letterboxd.com/film/${w.lb_slug}/`
    : w.tmdb_id
      ? `https://letterboxd.com/tmdb/${w.tmdb_id}/`
      : w.imdb_id
        ? `https://letterboxd.com/imdb/${w.imdb_id}/`
        : null;
