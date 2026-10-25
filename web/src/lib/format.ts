export function parseDate(value: string): Date {
  // Server timestamps are ISO with offset; bare dates are local calendar days.
  return /^\d{4}-\d{2}-\d{2}$/.test(value) ? new Date(`${value}T00:00:00`) : new Date(value);
}

export function relativeTime(value: string | null | undefined): string {
  if (!value) return "—";
  const diff = parseDate(value).getTime() - Date.now();
  const abs = Math.abs(diff);
  const units: [number, string][] = [
    [86_400_000, "d"],
    [3_600_000, "h"],
    [60_000, "m"],
  ];
  for (const [ms, label] of units) {
    if (abs >= ms) {
      const n = Math.round(abs / ms);
      return diff > 0 ? `in ${n}${label}` : `${n}${label} ago`;
    }
  }
  return diff > 0 ? "in <1m" : "just now";
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  return parseDate(value).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  return parseDate(value).toLocaleDateString(undefined, { dateStyle: "medium" });
}

export function duration(start: string, end: string | null): string {
  const ms = (end ? parseDate(end).getTime() : Date.now()) - parseDate(start).getTime();
  const s = Math.max(0, Math.round(ms / 1000));
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`;
}

export function stars(rating10: number | null | undefined): string {
  if (rating10 == null || rating10 <= 0) return "";
  const r = Math.round(rating10);
  return "★".repeat(Math.floor(r / 2)) + (r % 2 ? "½" : "");
}

export function summarize(summary: Record<string, unknown>): string {
  const parts: string[] = [];
  const scan = summary.scan as Record<string, number> | undefined;
  const baseline = summary.baseline as Record<string, number> | undefined;
  if (typeof summary.uploaded === "number") parts.push(`${summary.uploaded} logged`);
  if (typeof summary.failed === "number" && summary.failed) parts.push(`${summary.failed} unconfirmed`);
  if (typeof summary.already_in_diary === "number" && summary.already_in_diary) parts.push(`${summary.already_in_diary} already in diary`);
  if (typeof summary.waiting_rating === "number" && summary.waiting_rating) parts.push(`${summary.waiting_rating} waiting for rating`);
  if (baseline) parts.push(`baseline: ${baseline.matched} matched, ${baseline.baseline_skipped ?? 0} skipped`);
  if (typeof summary.matched === "number") parts.push(`${summary.matched}/${summary.checked} matched in diary`);
  const s = scan ?? (typeof summary.new_watches === "number" ? (summary as Record<string, number>) : undefined);
  if (s) parts.push(`${s.new_watches} new watch${s.new_watches === 1 ? "" : "es"}`);
  return parts.join(" · ");
}
