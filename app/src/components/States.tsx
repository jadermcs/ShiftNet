import { AlertTriangle, Loader2, RotateCcw } from 'lucide-react';

export function Loading({ label = 'Loading…', rows = 0 }: { label?: string; rows?: number }) {
  return (
    <div className="state" role="status" aria-live="polite">
      <div className="state-line">
        <Loader2 size={16} className="spin" aria-hidden="true" />
        {label}
      </div>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="skeleton" />
      ))}
    </div>
  );
}

export function ErrorState({ error, retry }: { error: unknown; retry?: () => void }) {
  const msg = error instanceof Error ? error.message : String(error);
  return (
    <div className="card state state-error" role="alert">
      <div className="state-line">
        <AlertTriangle size={16} aria-hidden="true" />
        Could not load data from ShiftNet.
      </div>
      <code className="small muted">{msg}</code>
      {retry && (
        <button className="btn" onClick={retry}>
          <RotateCcw size={14} aria-hidden="true" />
          Try again
        </button>
      )}
    </div>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <div className="card state muted">{children}</div>;
}
