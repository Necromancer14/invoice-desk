import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import type { Role, Status } from "./types";
import { makeT, type Lang } from "./i18n";

export interface Ctx {
  t: (s: string) => string; lang: Lang; role: Role; name: string; toast: (msg: string, kind?: "ok" | "err") => void;
  refreshCounts: () => void; go: (tab: string, arg?: string) => void;
}
export const AppCtx = createContext<Ctx>(null as unknown as Ctx);
export const useApp = () => useContext(AppCtx);
export const can = (role: Role, need: Role) => ({ viewer: 1, reviewer: 2, admin: 3 }[role] >= { viewer: 1, reviewer: 2, admin: 3 }[need]);

export const money = (n: number | null | undefined, cur?: string | null) =>
  n == null ? "–" : `${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}${cur ? " " + cur : ""}`;
export const when = (iso: string | null | undefined) => (iso ? new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "–");
export const pct = (n: number | null | undefined, d = 0) => (n == null ? "–" : `${(n * 100).toFixed(d)}%`);
export const dur = (s: number | null | undefined) => (s == null ? "–" : s < 90 ? `${s}s` : s < 5400 ? `${Math.round(s / 60)} min` : `${(s / 3600).toFixed(1)} h`);

export const STATUS_LABEL: Record<Status, string> = {
  approved: "Approved", needs_review: "Needs review", rejected: "Rejected", approved_human: "Approved by a person",
  rejected_human: "Rejected by a person", failed: "Failed", queued: "Queued", processing: "Processing",
};

const Icon = ({ d }: { d: string }) => (
  <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={d} /></svg>
);
const ICONS: Record<string, string> = {
  approved: "M3 8.5l3.2 3.2L13 5", approved_human: "M3 8.5l3.2 3.2L13 5", needs_review: "M8 3v6M8 12.5v.1", rejected: "M4 4l8 8M12 4l-8 8",
  rejected_human: "M4 4l8 8M12 4l-8 8", failed: "M8 3v6M8 12.5v.1", queued: "M8 4v4l3 2", processing: "M8 4v4l3 2",
  pass: "M3 8.5l3.2 3.2L13 5", fail: "M4 4l8 8M12 4l-8 8", skip: "M4 8h8",
};
export function StatusPill({ status }: { status: Status }) {
  const { t } = useApp();
  return <span className={`pill s-${status}`}><Icon d={ICONS[status]} />{t(STATUS_LABEL[status])}</span>;
}
export function CheckMark({ s }: { s: "pass" | "fail" | "skip" }) {
  return <span className={`pill ${s}`} style={{ padding: 3 }} role="img" aria-label={s}><Icon d={ICONS[s]} /></span>;
}

export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);
  return (
    <div className="modal-bg" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={title}>
        <div className="row"><h2>{title}</h2><button className="btn ghost small right" onClick={onClose} aria-label="Close">✕</button></div>
        {children}
      </div>
    </div>
  );
}

/** Load once, reload on demand, optionally poll while `poll` returns true. */
export function useLoad<T>(fn: () => Promise<T>, deps: unknown[] = [], poll?: (d: T) => boolean) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const fnRef = useRef(fn); fnRef.current = fn;
  const pollRef = useRef(poll); pollRef.current = poll;
  const reload = useCallback(async () => {
    try { const d = await fnRef.current(); setData(d); setError(null); return d; }
    catch (e) { setError((e as Error).message); return null; }
    finally { setLoading(false); }
  }, []);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { setLoading(true); reload(); }, deps);
  useEffect(() => {
    if (!data || !pollRef.current?.(data)) return;
    const id = setTimeout(reload, 1200);
    return () => clearTimeout(id);
  }, [data, reload]);
  return { data, error, loading, reload, setData };
}

export const Err = ({ msg }: { msg: string | null }) => (msg ? <div className="notice err" role="alert">{msg}</div> : null);
export const Empty = ({ title, hint, children }: { title: string; hint?: string; children?: ReactNode }) => (
  <div className="empty"><h3>{title}</h3>{hint && <p>{hint}</p>}{children}</div>
);
export function Head({ title, sub, children }: { title: string; sub?: string; children?: ReactNode }) {
  return <div className="page-head"><div className="grow"><h1>{title}</h1>{sub && <p>{sub}</p>}</div>{children}</div>;
}
export { makeT };
