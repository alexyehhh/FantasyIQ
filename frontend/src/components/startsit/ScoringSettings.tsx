"use client";

import { useState } from "react";
import type { ProjectionSource, Sport } from "@/lib/api";
import { EDITABLE_WEIGHTS, type ScoringChoice } from "@/lib/startSit";

interface ScoringSettingsProps {
  sport: Sport;
  sources: ProjectionSource[];
  choice: ScoringChoice;
  /** The points per unit the current scoring choice uses: what the fields show. */
  weights: Record<string, number>;
  onWeight: (stat: string, value: number) => void;
  onReset: () => void;
}

/**
 * A number field that lets the text be empty or half-typed ("0.", "-") while the weight it
 * reports only changes to valid numbers; on leaving it shows the weight actually in use.
 */
function WeightInput({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  return (
    <label className="flex flex-col gap-1 text-xs text-[#b9b0da]">
      {label}
      <input
        type="text"
        inputMode="decimal"
        value={draft ?? String(value)}
        onChange={(event) => {
          setDraft(event.target.value);
          const parsed = Number(event.target.value);
          if (event.target.value.trim() !== "" && Number.isFinite(parsed)) onChange(parsed);
        }}
        onBlur={() => setDraft(null)}
        className="h-9 rounded-lg bg-surface px-2 text-sm font-semibold text-ink"
      />
    </label>
  );
}

/** The gear panel: what each source is, and the scoring weights behind "Custom". */
export default function ScoringSettings({
  sport,
  sources,
  choice,
  weights,
  onWeight,
  onReset,
}: ScoringSettingsProps) {
  return (
    <div
      id="start-settings"
      className="grid gap-6 rounded-2xl border border-white/10 bg-white/[0.06] p-4 text-sm md:grid-cols-2"
    >
      <div>
        <h2 className="mb-2 font-display text-xl font-semibold uppercase tracking-wide">Source</h2>
        <ul className="space-y-2 text-[#d8d1f0]">
          {sources.map((source) => (
            <li key={source.name}>
              <strong className="text-white">{source.label}</strong>
              {source.description ? ` — ${source.description}` : ""}
            </li>
          ))}
        </ul>
      </div>
      <div>
        <div className="mb-2 flex items-center justify-between">
          <h2 className="font-display text-xl font-semibold uppercase tracking-wide">
            Custom scoring
          </h2>
          <button
            type="button"
            onClick={onReset}
            className="rounded-md px-2 py-1 text-xs font-semibold text-[#c9b8ff] hover:bg-white/10"
          >
            Reset to default
          </button>
        </div>
        <p className="mb-3 text-[#b9b0da]">
          Points per unit, following the scoring you pick above. Editing one switches scoring to
          Custom{sport === "NFL" ? "; kicker and defense scoring stay as in the default" : ""}.
        </p>
        <div className="grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-3">
          {EDITABLE_WEIGHTS[sport].map(({ key, label }) => (
            <WeightInput
              key={key}
              label={label}
              value={weights[key] ?? 0}
              onChange={(value) => onWeight(key, value)}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
