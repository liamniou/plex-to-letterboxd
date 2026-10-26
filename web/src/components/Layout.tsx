import { useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Clapperboard, History, LayoutDashboard, Loader2, RefreshCw, ScanSearch, Settings } from "lucide-react";
import { useEffect, useRef } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useBusy, useStartJob, useStatus } from "../lib/hooks";
import { Button } from "./ui";

const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard },
  { to: "/watches", label: "Watches", icon: Clapperboard },
  { to: "/runs", label: "Runs", icon: History },
  { to: "/settings", label: "Settings", icon: Settings },
];

const JOB_LABEL: Record<string, string> = { sync: "Syncing", scan: "Scanning Plex", reconcile: "Reading diary" };

function Logo() {
  return (
    <div className="flex items-center gap-2.5 px-2">
      <div className="flex -space-x-1">
        <span className="size-3 rounded-full bg-[#ff8000] mix-blend-screen" />
        <span className="size-3 rounded-full bg-[#00e054] mix-blend-screen" />
        <span className="size-3 rounded-full bg-[#40bcf4] mix-blend-screen" />
      </div>
      <span className="text-sm font-semibold tracking-tight">
        plex <span className="text-zinc-500">→</span> letterboxd
      </span>
    </div>
  );
}

export function Layout() {
  const { data: status } = useStatus();
  const { current, queued, busy } = useBusy();
  const startJob = useStartJob();
  const qc = useQueryClient();
  const location = useLocation();
  const title = NAV.find((n) => (n.to === "/" ? location.pathname === "/" : location.pathname.startsWith(n.to)))?.label ?? "";

  // Refresh data views when a job finishes.
  const prevRun = useRef<number | undefined>(undefined);
  useEffect(() => {
    const runId = current?.run_id;
    if (prevRun.current !== undefined && prevRun.current !== runId) {
      qc.invalidateQueries({ queryKey: ["watches"] });
      qc.invalidateQueries({ queryKey: ["runs"] });
      qc.invalidateQueries({ queryKey: ["run"] });
    }
    prevRun.current = runId;
  }, [current?.run_id, qc]);

  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 flex h-screen w-56 shrink-0 flex-col border-r border-zinc-800/80 bg-zinc-950 p-3 max-md:hidden">
        <div className="py-3">
          <Logo />
        </div>
        <nav className="mt-4 flex flex-col gap-0.5">
          {NAV.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              className={({ isActive }) =>
                clsx(
                  "flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm transition-colors",
                  isActive ? "bg-zinc-800/80 text-zinc-50" : "text-zinc-400 hover:bg-zinc-900 hover:text-zinc-200",
                )
              }
            >
              <Icon className="size-4" />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="mt-auto space-y-2 px-2 text-xs text-zinc-500">
          <div className="flex items-center gap-2">
            <span className={clsx("size-1.5 rounded-full", busy ? "animate-pulse bg-sky-400" : "bg-emerald-500")} />
            {current ? JOB_LABEL[current.kind] ?? current.kind : busy ? "Queued" : "Idle"}
          </div>
          <div>v{status?.version ?? "…"}</div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-10 flex h-14 items-center justify-between gap-3 border-b border-zinc-800/80 bg-zinc-950/80 px-6 backdrop-blur max-md:px-4">
          <div className="flex min-w-0 items-center gap-4">
            <div className="md:hidden">
              <Logo />
            </div>
            <h1 className="text-base font-semibold max-md:hidden">{title}</h1>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {current && (
              <span className="flex items-center gap-1.5 text-xs text-sky-400 max-sm:hidden">
                <Loader2 className="size-3.5 animate-spin" />
                {JOB_LABEL[current.kind] ?? current.kind}…{queued.length > 0 && <span className="text-zinc-500">(+{queued.length} queued)</span>}
              </span>
            )}
            <Button size="sm" variant="ghost" onClick={() => startJob.mutate("scan")} disabled={busy} title="Read Plex watch history without uploading" aria-label="Scan Plex">
              <ScanSearch className="size-3.5" />
              <span className="max-sm:hidden">Scan Plex</span>
            </Button>
            <Button size="sm" variant="primary" onClick={() => startJob.mutate("sync")} disabled={busy} aria-label="Sync now" className="whitespace-nowrap">
              <RefreshCw className={clsx("size-3.5", current?.kind === "sync" && "animate-spin")} />
              <span className="max-[359px]:hidden">Sync now</span>
            </Button>
          </div>
        </header>
        <main className="mx-auto w-full max-w-7xl flex-1 p-6 max-md:px-3 max-md:pb-24 max-md:pt-4">
          <Outlet />
        </main>
      </div>

      <nav className="fixed inset-x-0 bottom-0 z-20 grid grid-cols-4 border-t border-zinc-800 bg-zinc-950/95 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden">
        {NAV.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === "/"}
            className={({ isActive }) =>
              clsx("flex flex-col items-center gap-1 py-2 text-[11px] transition-colors", isActive ? "text-emerald-400" : "text-zinc-500")
            }
          >
            <Icon className="size-5" />
            {label}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
