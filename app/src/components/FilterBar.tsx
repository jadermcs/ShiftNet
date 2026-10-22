import { useEffect, useState, type ReactNode } from 'react';
import { Filter, X } from 'lucide-react';
import { hasFilters, type ViewParams } from '../lib/params';
import { SHIFT_TYPES, type Pos } from '../lib/types';

interface Props {
  params: ViewParams;
  update: (patch: Partial<ViewParams>) => void;
  posOptions: Pos[];
  /** Controls shown before the filters (time travel, order, jump to). */
  children?: ReactNode;
  note?: string | null;
}

/** Year input that commits on blur / Enter so typing "1" on the way to "1990" doesn't filter. */
function YearInput({ value, onCommit, label }: { value: number | null; onCommit: (v: number | null) => void; label: string }) {
  const [text, setText] = useState(value == null ? '' : String(value));
  useEffect(() => setText(value == null ? '' : String(value)), [value]);
  const commit = () => {
    const v = text.trim() === '' ? null : Math.trunc(Number(text));
    if (v !== value && (v == null || Number.isFinite(v))) onCommit(v);
  };
  return (
    <input
      className="input input-year mono"
      type="number"
      inputMode="numeric"
      placeholder={label.toLowerCase()}
      aria-label={`${label} year`}
      value={text}
      onChange={(e) => setText(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => e.key === 'Enter' && commit()}
    />
  );
}

/** Filters (US9): part of speech, shift type, date range; active filters as removable chips. */
export function FilterBar({ params: p, update, posOptions, children, note }: Props) {
  const chips = [
    ...p.pos.map((x) => ({ label: `POS: ${x}`, rm: () => update({ pos: p.pos.filter((y) => y !== x) }) })),
    ...p.shift.map((x) => ({ label: `Shift: ${x}`, rm: () => update({ shift: p.shift.filter((y) => y !== x) }) })),
    ...(p.from != null ? [{ label: `From ${p.from}`, rm: () => update({ from: null }) }] : []),
    ...(p.to != null ? [{ label: `To ${p.to}`, rm: () => update({ to: null }) }] : []),
  ];

  return (
    <div className="card controls">
      <div className="controls-row">
        {children}
        <div className="filters" role="group" aria-label="Filters">
          <Filter size={15} className="icon-muted" aria-hidden="true" />
          {posOptions.map((x) => {
            const on = p.pos.includes(x);
            return (
              <button
                key={x}
                className={`pill pill-toggle${on ? ' on' : ''}`}
                aria-pressed={on}
                onClick={() => update({ pos: on ? p.pos.filter((y) => y !== x) : [...p.pos, x] })}
              >
                {x}
              </button>
            );
          })}
          <select
            className="input input-sm"
            value=""
            aria-label="Add shift type filter"
            onChange={(e) => e.target.value && update({ shift: [...p.shift, e.target.value as (typeof SHIFT_TYPES)[number]] })}
          >
            <option value="">Shift type…</option>
            {SHIFT_TYPES.filter((x) => !p.shift.includes(x)).map((x) => (
              <option key={x} value={x}>
                {x}
              </option>
            ))}
          </select>
          <YearInput label="From" value={p.from} onCommit={(from) => update({ from })} />
          <YearInput label="To" value={p.to} onCommit={(to) => update({ to })} />
        </div>
      </div>
      {hasFilters(p) && (
        <div className="controls-chips">
          {chips.map((c) => (
            <button key={c.label} className="chip-remove" onClick={c.rm} aria-label={`Remove filter ${c.label}`}>
              {c.label}
              <X size={13} aria-hidden="true" />
            </button>
          ))}
          <button className="link-btn underline small" onClick={() => update({ pos: [], shift: [], from: null, to: null })}>
            Clear all
          </button>
          <span className="small muted">Filtered-out senses stay in place, dashed, so the lineage stays readable.</span>
        </div>
      )}
      {note && <div className="controls-note">{note}</div>}
    </div>
  );
}
