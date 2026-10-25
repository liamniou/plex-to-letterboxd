import clsx from "clsx";
import { Loader2 } from "lucide-react";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { useState } from "react";
import type { Run, Watch, WatchStatus } from "../lib/api";
import { posterUrl } from "../lib/api";

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={clsx("rounded-xl border border-zinc-800 bg-zinc-900/60", className)}>{children}</div>;
}

export function CardHeader({ title, icon, action }: { title: string; icon?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-2 border-b border-zinc-800 px-4 py-3">
      <h2 className="flex items-center gap-2 text-sm font-medium text-zinc-300">
        {icon}
        {title}
      </h2>
      {action}
    </div>
  );
}

type Variant = "primary" | "secondary" | "ghost" | "danger";

export function Button({
  variant = "secondary",
  size = "md",
  loading,
  className,
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md"; loading?: boolean }) {
  return (
    <button
      {...props}
      disabled={props.disabled || loading}
      className={clsx(
        "inline-flex items-center justify-center gap-1.5 rounded-md font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50",
        size === "sm" ? "h-7 px-2.5 text-xs" : "h-9 px-3.5 text-sm",
        variant === "primary" && "bg-emerald-500 text-zinc-950 hover:bg-emerald-400",
        variant === "secondary" && "border border-zinc-700 bg-zinc-800/70 text-zinc-200 hover:bg-zinc-700/70",
        variant === "ghost" && "text-zinc-400 hover:bg-zinc-800 hover:text-zinc-100",
        variant === "danger" && "border border-red-900/60 bg-red-950/40 text-red-300 hover:bg-red-900/40",
        className,
      )}
    >
      {loading && <Loader2 className="size-3.5 animate-spin" />}
      {children}
    </button>
  );
}

const STATUS_STYLES: Record<string, string> = {
  synced: "bg-emerald-500/10 text-emerald-400 ring-emerald-500/20",
  success: "bg-emerald-500/10 text-emerald-400 ring-emerald-500/20",
  pending: "bg-sky-500/10 text-sky-400 ring-sky-500/20",
  running: "bg-sky-500/10 text-sky-400 ring-sky-500/20",
  failed: "bg-red-500/10 text-red-400 ring-red-500/20",
  skipped: "bg-zinc-500/10 text-zinc-400 ring-zinc-500/20",
  rating: "bg-amber-500/10 text-amber-400 ring-amber-500/20",
};

export function Badge({ tone, children, className }: { tone: string; children: ReactNode; className?: string }) {
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs font-medium ring-1 ring-inset",
        STATUS_STYLES[tone] ?? STATUS_STYLES.skipped,
        className,
      )}
    >
      {children}
    </span>
  );
}

export function WatchStatusBadge({ watch, requireRating = true }: { watch: Watch; requireRating?: boolean }) {
  const waitingRating = requireRating && watch.user_rating == null && (watch.status === "pending" || watch.status === "failed");
  if (waitingRating) return <Badge tone="rating">needs rating</Badge>;
  return <Badge tone={watch.status}>{watch.status}</Badge>;
}

export function RunStatusBadge({ run }: { run: Pick<Run, "status"> }) {
  return (
    <Badge tone={run.status}>
      {run.status === "running" && <Loader2 className="size-3 animate-spin" />}
      {run.status}
    </Badge>
  );
}

export const STATUS_LABELS: Record<WatchStatus, string> = {
  pending: "Pending",
  synced: "Synced",
  failed: "Failed",
  skipped: "Skipped",
};

export function Poster({ ratingKey, hasPoster, className }: { ratingKey: number; hasPoster: boolean | number; className?: string }) {
  const [failed, setFailed] = useState(false);
  return (
    <div className={clsx("overflow-hidden rounded bg-zinc-800 ring-1 ring-zinc-700/50", className)}>
      {hasPoster && !failed ? (
        <img src={posterUrl(ratingKey)} alt="" loading="lazy" className="size-full object-cover" onError={() => setFailed(true)} />
      ) : null}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="px-4 py-12 text-center text-sm text-zinc-500">{children}</div>;
}

export function Spinner() {
  return (
    <div className="flex justify-center py-12">
      <Loader2 className="size-5 animate-spin text-zinc-500" />
    </div>
  );
}

export function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label?: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={() => onChange(!checked)}
      className={clsx(
        "relative inline-flex h-5 w-9 shrink-0 rounded-full transition-colors",
        checked ? "bg-emerald-500" : "bg-zinc-700",
      )}
    >
      <span className={clsx("absolute top-0.5 size-4 rounded-full bg-white transition-transform", checked ? "translate-x-4.5" : "translate-x-0.5")} />
    </button>
  );
}
