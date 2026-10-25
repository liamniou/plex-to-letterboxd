import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { useEffect, useRef } from "react";
import { Link, useParams } from "react-router-dom";
import { Card, CardHeader, Empty, RunStatusBadge, Spinner } from "../components/ui";
import { api } from "../lib/api";
import { duration, formatDateTime, relativeTime, summarize } from "../lib/format";

const KIND_LABEL: Record<string, string> = { sync: "Sync", scan: "Plex scan", reconcile: "Diary reconcile" };

export function Runs() {
  const { id } = useParams();
  const runs = useQuery({
    queryKey: ["runs"],
    queryFn: () => api.runs(100),
    refetchInterval: (q) => (q.state.data?.items.some((r) => r.status === "running") ? 2000 : 15000),
  });
  const selectedId = id ? Number(id) : runs.data?.items[0]?.id;

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
      <Card className="self-start overflow-hidden">
        <CardHeader title="History" />
        {runs.isLoading ? (
          <Spinner />
        ) : !runs.data?.items.length ? (
          <Empty>No runs yet.</Empty>
        ) : (
          <ul className="max-h-[calc(100vh-12rem)] divide-y divide-zinc-800/70 overflow-y-auto">
            {runs.data.items.map((r) => (
              <li key={r.id}>
                <Link
                  to={`/runs/${r.id}`}
                  className={clsx("block px-4 py-3 transition-colors hover:bg-zinc-800/30", r.id === selectedId && "bg-zinc-800/50")}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-medium">
                      {KIND_LABEL[r.kind] ?? r.kind} <span className="font-normal text-zinc-500">#{r.id}</span>
                    </span>
                    <RunStatusBadge run={r} />
                  </div>
                  <div className="mt-1 flex justify-between gap-2 text-xs text-zinc-500">
                    <span title={formatDateTime(r.started_at)}>
                      {relativeTime(r.started_at)} · {r.trigger}
                    </span>
                    <span>{duration(r.started_at, r.finished_at)}</span>
                  </div>
                  {(r.error || Object.keys(r.summary).length > 0) && (
                    <div className={clsx("mt-1 truncate text-xs", r.error ? "text-red-400/90" : "text-zinc-400")}>{r.error ?? summarize(r.summary)}</div>
                  )}
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Card>
      {selectedId ? <RunDetail id={selectedId} /> : null}
    </div>
  );
}

const LEVEL_COLOR: Record<string, string> = { ERROR: "text-red-400", WARNING: "text-amber-400", CRITICAL: "text-red-500" };

function RunDetail({ id }: { id: number }) {
  const { data, isLoading } = useQuery({
    queryKey: ["run", id],
    queryFn: () => api.run(id),
    refetchInterval: (q) => (q.state.data?.run.status === "running" ? 2000 : false),
  });
  const bottom = useRef<HTMLDivElement>(null);
  const running = data?.run.status === "running";
  useEffect(() => {
    if (running) bottom.current?.scrollIntoView({ block: "nearest" });
  }, [data?.logs.length, running]);

  if (isLoading || !data) return <Spinner />;
  const { run, logs } = data;
  const summary = summarize(run.summary);

  return (
    <Card className="self-start overflow-hidden">
      <CardHeader title={`${KIND_LABEL[run.kind] ?? run.kind} #${run.id}`} action={<RunStatusBadge run={run} />} />
      <div className="grid grid-cols-2 gap-x-6 gap-y-1 border-b border-zinc-800 px-4 py-3 text-xs sm:grid-cols-4">
        <div>
          <div className="text-zinc-500">Started</div>
          <div>{formatDateTime(run.started_at)}</div>
        </div>
        <div>
          <div className="text-zinc-500">Duration</div>
          <div>{duration(run.started_at, run.finished_at)}</div>
        </div>
        <div>
          <div className="text-zinc-500">Trigger</div>
          <div>{run.trigger}</div>
        </div>
        <div>
          <div className="text-zinc-500">Result</div>
          <div className={run.error ? "text-red-400" : ""}>{run.error ?? (summary || "—")}</div>
        </div>
      </div>
      <div className="max-h-[calc(100vh-16rem)] overflow-auto bg-zinc-950/60 p-4 font-mono text-xs leading-relaxed">
        {logs.length === 0 ? (
          <div className="text-zinc-600">No log output.</div>
        ) : (
          logs.map((l) => (
            <div key={l.id} className="flex gap-3 whitespace-pre-wrap break-words">
              <span className="shrink-0 text-zinc-600">{new Date(l.ts).toLocaleTimeString()}</span>
              <span className={clsx("min-w-0", LEVEL_COLOR[l.level] ?? "text-zinc-300")}>{l.message}</span>
            </div>
          ))
        )}
        <div ref={bottom} />
      </div>
    </Card>
  );
}
