import clsx from "clsx";
import { Star, X } from "lucide-react";
import { useEffect, useState } from "react";
import { stars } from "../lib/format";
import { Button } from "./ui";

/** Five stars with half-star steps; value is on Plex's 0-10 scale (0 = unrated). */
function StarPicker({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  const [hover, setHover] = useState<number | null>(null);
  const shown = hover ?? value;
  return (
    <div className="flex justify-center gap-1" onMouseLeave={() => setHover(null)}>
      {[1, 2, 3, 4, 5].map((i) => {
        const fill = shown >= i * 2 ? 1 : shown === i * 2 - 1 ? 0.5 : 0;
        return (
          <div key={i} className="relative size-11">
            <Star className="absolute inset-0 size-11 text-zinc-700" strokeWidth={1.5} />
            <div className="absolute inset-0 overflow-hidden" style={{ width: `${fill * 100}%` }}>
              <Star className="size-11 fill-emerald-400 text-emerald-400" strokeWidth={1.5} />
            </div>
            {[i * 2 - 1, i * 2].map((v, half) => (
              <button
                key={v}
                type="button"
                aria-label={`${v / 2} stars`}
                className={clsx("absolute inset-y-0 w-1/2 cursor-pointer", half ? "right-0" : "left-0")}
                onMouseEnter={() => setHover(v)}
                onFocus={() => setHover(v)}
                onBlur={() => setHover(null)}
                onClick={() => onChange(v)}
              />
            ))}
          </div>
        );
      })}
    </div>
  );
}

export function RatingDialog({
  title,
  year,
  initial,
  synced,
  saving,
  error,
  onSave,
  onClose,
}: {
  title: string;
  year: number | null;
  initial: number | null;
  synced: boolean;
  saving: boolean;
  error: string | null;
  onSave: (rating10: number) => void;
  onClose: () => void;
}) {
  const [value, setValue] = useState(initial ? Math.round(initial) : 0);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/60 backdrop-blur-sm sm:items-center" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`Rate ${title}`}
        className="w-full max-w-sm rounded-t-2xl border border-zinc-800 bg-zinc-900 p-5 shadow-2xl sm:rounded-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="text-xs uppercase tracking-wide text-zinc-500">Rate in Plex</div>
            <div className="truncate text-base font-semibold">
              {title} {year && <span className="font-normal text-zinc-500">({year})</span>}
            </div>
          </div>
          <Button size="sm" variant="ghost" onClick={onClose} aria-label="Close">
            <X className="size-4" />
          </Button>
        </div>

        <div className="my-6">
          <StarPicker value={value} onChange={setValue} />
          <div className="mt-3 text-center text-sm tabular-nums text-zinc-400">
            {value ? (
              <>
                <span className="text-emerald-400">{stars(value)}</span> {value / 2} / 5
              </>
            ) : (
              "No rating"
            )}
          </div>
        </div>

        {synced && <p className="mb-3 text-xs text-amber-400/90">Already logged on Letterboxd; this only changes the rating in Plex.</p>}
        {error && <p className="mb-3 text-xs text-red-400">{error}</p>}

        <div className="flex items-center justify-between gap-2">
          <Button variant="ghost" onClick={() => setValue(0)} disabled={!value || saving}>
            Clear
          </Button>
          <div className="flex gap-2">
            <Button onClick={onClose}>Cancel</Button>
            <Button variant="primary" loading={saving} disabled={value === (initial ? Math.round(initial) : 0)} onClick={() => onSave(value)}>
              Save
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
