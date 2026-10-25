import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Ban, Check, ChevronLeft, ChevronRight, ExternalLink, RotateCcw, Search } from "lucide-react";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Button, Card, Empty, Poster, Spinner, WatchStatusBadge } from "../components/ui";
import { api, letterboxdUrl, plexUrl, type Watch, type WatchAction } from "../lib/api";
import { formatDate, formatDateTime, stars } from "../lib/format";
import { useSettings, useStatus } from "../lib/hooks";

const TABS = [
  { key: "", label: "All" },
  { key: "pending", label: "Pending" },
  { key: "needs_rating", label: "Needs rating" },
  { key: "synced", label: "Synced" },
  { key: "failed", label: "Failed" },
  { key: "skipped", label: "Skipped" },
] as const;

const PAGE_SIZE = 50;

const ACTION_BUTTONS: { action: WatchAction; label: string; icon: typeof Check; show: (w: Watch) => boolean }[] = [
  { action: "queue", label: "Queue", icon: RotateCcw, show: (w) => w.status !== "pending" },
  { action: "skip", label: "Skip", icon: Ban, show: (w) => w.status === "pending" || w.status === "failed" },
  { action: "mark_synced", label: "Mark synced", icon: Check, show: (w) => w.status !== "synced" },
];

function useDebounced<T>(value: T, ms = 300) {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

export function Watches() {
  const [params, setParams] = useSearchParams();
  const tab = params.get("status") ?? "";
  const page = Number(params.get("page") ?? 1);
  const [search, setSearch] = useState(params.get("q") ?? "");
  const q = useDebounced(search);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const { data: status } = useStatus();
  const { data: settings } = useSettings();
  const qc = useQueryClient();

  const setParam = (updates: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    Object.entries(updates).forEach(([k, v]) => (v ? next.set(k, v) : next.delete(k)));
    setParams(next, { replace: true });
  };

  useEffect(() => {
    if (q !== (params.get("q") ?? "")) setParam({ q: q || null, page: null });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q]);
  useEffect(() => setSelected(new Set()), [tab, page, q]);

  const query = useQuery({
    queryKey: ["watches", tab, q, page],
    queryFn: () =>
      api.watches({
        status: tab === "needs_rating" ? "pending" : tab,
        needs_rating: tab === "needs_rating" ? true : undefined,
        q,
        page,
        page_size: PAGE_SIZE,
      }),
    placeholderData: keepPreviousData,
  });

  const action = useMutation({
    mutationFn: ({ ids, action }: { ids: number[]; action: WatchAction }) => api.watchAction(ids, action),
    onSuccess: () => {
      setSelected(new Set());
      qc.invalidateQueries({ queryKey: ["watches"] });
      qc.invalidateQueries({ queryKey: ["status"] });
    },
  });

  const items = query.data?.items ?? [];
  const total = query.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const allSelected = items.length > 0 && items.every((w) => selected.has(w.id));
  const counts = status?.counts;
  const tabCount = (key: string) =>
    !counts ? undefined : key === "" ? counts.pending + counts.synced + counts.failed + counts.skipped : key === "needs_rating" ? counts.needs_rating : counts[key as keyof typeof counts];

  const toggle = (id: number) =>
    setSelected((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-1 rounded-lg border border-zinc-800 bg-zinc-900/60 p-1">
          {TABS.map((t) => (
            <button
              key={t.key}
              onClick={() => setParam({ status: t.key || null, page: null })}
              className={clsx(
                "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
                tab === t.key ? "bg-zinc-700/80 text-zinc-50" : "text-zinc-400 hover:text-zinc-200",
              )}
            >
              {t.label}
              {tabCount(t.key) !== undefined && <span className="tabular-nums text-zinc-500">{tabCount(t.key)}</span>}
            </button>
          ))}
        </div>
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-zinc-500" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search title, IMDb or TMDB id"
            className="h-9 w-72 rounded-md border border-zinc-800 bg-zinc-900 pl-8 pr-3 text-sm outline-none placeholder:text-zinc-600 focus:border-zinc-600"
          />
        </div>
      </div>

      {selected.size > 0 && (
        <div className="flex items-center gap-2 rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm">
          <span className="mr-2 text-zinc-300">{selected.size} selected</span>
          {ACTION_BUTTONS.map(({ action: a, label, icon: Icon }) => (
            <Button key={a} size="sm" onClick={() => action.mutate({ ids: [...selected], action: a })} loading={action.isPending && action.variables?.action === a}>
              <Icon className="size-3.5" />
              {label}
            </Button>
          ))}
          <Button size="sm" variant="ghost" onClick={() => setSelected(new Set())}>
            Clear
          </Button>
        </div>
      )}

      <Card className="overflow-hidden">
        {query.isLoading ? (
          <Spinner />
        ) : items.length === 0 ? (
          <Empty>No watches here.</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-zinc-800 text-left text-xs text-zinc-500">
                  <th className="w-10 px-4 py-2.5">
                    <input
                      type="checkbox"
                      className="accent-emerald-500"
                      checked={allSelected}
                      onChange={() => setSelected(allSelected ? new Set() : new Set(items.map((w) => w.id)))}
                      aria-label="Select all"
                    />
                  </th>
                  <th className="py-2.5 font-medium">Film</th>
                  <th className="px-3 py-2.5 font-medium">Watched</th>
                  <th className="px-3 py-2.5 font-medium">Rating</th>
                  <th className="px-3 py-2.5 font-medium">Status</th>
                  <th className="px-4 py-2.5 text-right font-medium">Actions</th>
                </tr>
              </thead>
              <tbody className={clsx("divide-y divide-zinc-800/70", query.isPlaceholderData && "opacity-60")}>
                {items.map((w) => (
                  <WatchRow
                    key={w.id}
                    w={w}
                    selected={selected.has(w.id)}
                    onToggle={() => toggle(w.id)}
                    onAction={(a) => action.mutate({ ids: [w.id], action: a })}
                    busy={action.isPending && action.variables?.ids.length === 1 && action.variables.ids[0] === w.id}
                    requireRating={settings?.require_rating ?? true}
                    plexMachineId={status?.config.plex_machine_id}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
        {total > PAGE_SIZE && (
          <div className="flex items-center justify-between border-t border-zinc-800 px-4 py-2.5 text-xs text-zinc-400">
            <span>
              {(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, total)} of {total}
            </span>
            <div className="flex items-center gap-1">
              <Button size="sm" variant="ghost" disabled={page <= 1} onClick={() => setParam({ page: String(page - 1) })} aria-label="Previous page">
                <ChevronLeft className="size-4" />
              </Button>
              <span className="tabular-nums">
                {page} / {pages}
              </span>
              <Button size="sm" variant="ghost" disabled={page >= pages} onClick={() => setParam({ page: String(page + 1) })} aria-label="Next page">
                <ChevronRight className="size-4" />
              </Button>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}

function WatchRow({
  w,
  selected,
  onToggle,
  onAction,
  busy,
  requireRating,
  plexMachineId,
}: {
  w: Watch;
  selected: boolean;
  onToggle: () => void;
  onAction: (a: WatchAction) => void;
  busy: boolean;
  requireRating: boolean;
  plexMachineId: string | null | undefined;
}) {
  const lb = letterboxdUrl(w);
  const plex = plexUrl(plexMachineId, w.rating_key);
  const detail = w.last_error ?? w.note;
  return (
    <tr className={clsx("transition-colors hover:bg-zinc-800/30", selected && "bg-zinc-800/40")}>
      <td className="px-4 py-2">
        <input type="checkbox" className="accent-emerald-500" checked={selected} onChange={onToggle} aria-label={`Select ${w.title}`} />
      </td>
      <td className="py-2">
        <div className="flex items-center gap-3">
          <Poster ratingKey={w.rating_key} hasPoster={w.has_poster} className="h-12 w-8 shrink-0" />
          <div className="min-w-0">
            <div className="truncate font-medium text-zinc-100">
              {w.title} {w.year && <span className="font-normal text-zinc-500">({w.year})</span>}
            </div>
            <div className="mt-0.5 flex items-center gap-2 text-xs text-zinc-500">
              {plex && (
                <a href={plex} target="_blank" rel="noreferrer" className="flex items-center gap-0.5 hover:text-[#e5a00d]">
                  Plex <ExternalLink className="size-3" />
                </a>
              )}
              {lb && (
                <a href={lb} target="_blank" rel="noreferrer" className="flex items-center gap-0.5 hover:text-[#00e054]">
                  Letterboxd <ExternalLink className="size-3" />
                </a>
              )}
              {w.rewatch ? <span>rewatch</span> : null}
            </div>
          </div>
        </div>
      </td>
      <td className="whitespace-nowrap px-3 py-2 text-zinc-300">
        <div title={w.watched_at ? formatDateTime(w.watched_at) : undefined}>{formatDate(w.watched_date)}</div>
        <div className="text-xs text-zinc-500">{w.source === "history" ? "Plex history" : w.source === "plex" ? "Plex" : w.source}</div>
      </td>
      <td className="whitespace-nowrap px-3 py-2 text-emerald-400">{stars(w.user_rating) || <span className="text-zinc-600">—</span>}</td>
      <td className="max-w-xs px-3 py-2">
        <WatchStatusBadge watch={w} requireRating={requireRating} />
        {detail && (
          <div className={clsx("mt-1 truncate text-xs", w.last_error ? "text-red-400/90" : "text-zinc-500")} title={detail}>
            {detail}
            {w.attempts > 0 && w.status === "failed" ? ` (attempt ${w.attempts})` : ""}
          </div>
        )}
        {w.synced_at && w.status === "synced" && <div className="text-xs text-zinc-600">{formatDateTime(w.synced_at)}</div>}
      </td>
      <td className="px-4 py-2">
        <div className="flex justify-end gap-1">
          {ACTION_BUTTONS.filter((b) => b.show(w)).map(({ action, label, icon: Icon }) => (
            <Button key={action} size="sm" variant="ghost" title={label} aria-label={label} onClick={() => onAction(action)} disabled={busy}>
              <Icon className="size-3.5" />
            </Button>
          ))}
        </div>
      </td>
    </tr>
  );
}
