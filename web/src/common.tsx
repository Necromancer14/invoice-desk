import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import type { Role, Status } from "./types";
import { LOCALE, makeT, tk, type Lang, type Vars } from "./i18n";

export interface Ctx {
  t: (s: string, vars?: Vars) => string; lang: Lang; role: Role; name: string; toast: (msg: string, kind?: "ok" | "err") => void;
  /** Fetch the review count again; change adjusts the badge at once (a decision is -1) until the answer arrives. */
  refreshCounts: (change?: number) => void;
  /** The Review page knows the exact count from its own list. */
  setQueueCount: (n: number) => void;
  go: (tab: string, arg?: string) => void;
}
export const AppCtx = createContext<Ctx>(null as unknown as Ctx);
export const useApp = () => useContext(AppCtx);
export const can = (role: Role, need: Role) => ({ viewer: 1, reviewer: 2, admin: 3 }[role] >= { viewer: 1, reviewer: 2, admin: 3 }[need]);

/** The language numbers and dates are formatted in. App sets it whenever the language changes, then re-renders. */
let fmtLang: Lang = "en";
export const setFormatLang = (l: Lang) => { fmtLang = l; };
const loc = () => LOCALE[fmtLang];

export const num = (n: number | null | undefined, digits = 0) =>
  n == null ? "–" : n.toLocaleString(loc(), { minimumFractionDigits: digits, maximumFractionDigits: digits });
/** Amount plus currency code. Wrap it in <bdi dir="ltr"> where it sits inside Arabic text so the code stays after the number. */
export const money = (n: number | null | undefined, cur?: string | null) => (n == null ? "–" : `${num(n, 2)}${cur ? " " + cur : ""}`);
export const when = (iso: string | null | undefined) => (iso ? new Date(iso).toLocaleString(loc(), { dateStyle: "medium", timeStyle: "short" }) : "–");
/** A calendar date. Plain YYYY-MM-DD values are read as that day, not as UTC midnight shifted into local time. */
export const day = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleDateString(loc(), { dateStyle: "medium", ...(/^\d{4}-\d{2}-\d{2}$/.test(iso) ? { timeZone: "UTC" } : {}) }) : "–";
/** A large amount in short form, "1.38M SAR", for a figure tile. The full amount goes in a title or nearby text. */
export const compactMoney = (n: number, cur: string) =>
  `${n.toLocaleString(loc(), { notation: "compact", maximumFractionDigits: n >= 1e6 ? 2 : 1 })} ${cur}`;
/** "Monday 9 November", in the active language. */
export const longDay = (d: Date = new Date()) => d.toLocaleDateString(loc(), { weekday: "long", day: "numeric", month: "long" });
/** True while the page is laid out right to left. */
export const isRtl = () => fmtLang === "ar";
export const pct = (n: number | null | undefined, d = 0) =>
  n == null ? "–" : n.toLocaleString(loc(), { style: "percent", minimumFractionDigits: d, maximumFractionDigits: d });
const unit = (n: number, u: "second" | "minute" | "hour") => n.toLocaleString(loc(), { style: "unit", unit: u, unitDisplay: "short", maximumFractionDigits: 1 });
export const dur = (s: number | null | undefined) => (s == null ? "–" : s < 90 ? unit(s, "second") : s < 5400 ? unit(Math.round(s / 60), "minute") : unit(s / 3600, "hour"));
/** "5 minutes ago", in the active language. */
export function ago(iso: string | null | undefined): string {
  if (!iso) return "–";
  const s = Math.round((new Date(iso).getTime() - Date.now()) / 1000);
  const rtf = new Intl.RelativeTimeFormat(loc(), { numeric: "auto", style: "short" });
  const a = Math.abs(s);
  if (a < 60) return rtf.format(s, "second");
  if (a < 3600) return rtf.format(Math.round(s / 60), "minute");
  if (a < 86400) return rtf.format(Math.round(s / 3600), "hour");
  return rtf.format(Math.round(s / 86400), "day");
}

export const STATUS_LABEL: Record<Status, string> = {
  approved: tk("Approved"), needs_review: tk("Needs review"), rejected: tk("Rejected"), approved_human: tk("Approved by a person"),
  rejected_human: tk("Rejected by a person"), failed: tk("Failed"), queued: tk("Queued"), processing: tk("Processing"),
};

/** Display names for the invoice fields. The field ids themselves stay as they are in expressions and the API. */
export const FIELD_LABEL: Record<string, string> = {
  invoice_number: tk("Invoice number"), issue_date: tk("Issue date"), due_date: tk("Due date"), seller_name: tk("Seller"),
  seller_vat: tk("Seller VAT number"), buyer_name: tk("Buyer"), buyer_vat: tk("Buyer VAT number"), currency: tk("Currency"),
  subtotal: tk("Subtotal"), vat_amount: tk("VAT amount"), total: tk("Total"), qr_payload: tk("QR code"), line_items: tk("Line items"),
  invoice_type: tk("Invoice type"), iban: tk("IBAN"), po_number: tk("PO number"),
};
const CHECK_LABEL = { pass: tk("Check passed"), fail: tk("Check failed"), skip: tk("Check skipped") };

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
  const { t } = useApp();
  return <span className={`pill mark ${s}`} role="img" aria-label={t(CHECK_LABEL[s])}><Icon d={ICONS[s]} /></span>;
}

const FOCUSABLE = "button, [href], input, select, textarea, [tabindex]:not([tabindex='-1'])";

/**
 * A dialog that behaves for keyboard users: focus moves into it when it opens (the first field, else the dialog),
 * Tab and Shift+Tab stay inside it, Escape closes it, and focus goes back to whatever opened it.
 */
export function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  const { t } = useApp();
  const box = useRef<HTMLDivElement>(null);
  const close = useRef(onClose); close.current = onClose;
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    (box.current?.querySelector<HTMLElement>("input:not([disabled]), select:not([disabled]), textarea:not([disabled])") ?? box.current)?.focus();
    const h = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.preventDefault(); close.current(); return; }
      if (e.key !== "Tab" || !box.current) return;
      const items = [...box.current.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((el) => !el.hasAttribute("disabled") && el.offsetParent !== null);
      if (!items.length) return;
      const at = items.indexOf(document.activeElement as HTMLElement);
      if (e.shiftKey && at <= 0) { e.preventDefault(); items[items.length - 1].focus(); }
      else if (!e.shiftKey && (at === -1 || at === items.length - 1)) { e.preventDefault(); items[0].focus(); }
    };
    window.addEventListener("keydown", h);
    return () => { window.removeEventListener("keydown", h); if (opener?.isConnected) opener.focus(); };
  }, []);
  return (
    <div className="modal-bg" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal${wide ? " wide" : ""}`} role="dialog" aria-modal="true" aria-label={title} ref={box} tabIndex={-1}>
        <div className="row"><h2>{title}</h2><button className="btn ghost small right" onClick={onClose} aria-label={t("Close")}>✕</button></div>
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

/** An error notice. Known messages are translated; text the server wrote shows as sent (in its own direction). */
export function Err({ msg }: { msg: string | null }) {
  const ctx = useContext(AppCtx);  // also used on the sign-in screen, which sits outside the provider
  if (!msg) return null;
  return <div className="notice err" role="alert" dir="auto">{ctx ? ctx.t(msg) : msg}</div>;
}
export const Empty = ({ title, hint, children }: { title: string; hint?: string; children?: ReactNode }) => (
  <div className="empty"><h3>{title}</h3>{hint && <p>{hint}</p>}{children}</div>
);
export function Head({ title, sub, children }: { title: string; sub?: string; children?: ReactNode }) {
  return <div className="page-head"><div className="grow"><h1>{title}</h1>{sub && <p>{sub}</p>}</div>{children}</div>;
}
export { makeT, tk };

/** Where a run came from: uploads (files and samples sent through intake) or the Evaluation page. */
export type Source = "upload" | "evaluation" | "all";
export const SOURCES: { value: Source; label: string }[] = [
  { value: "upload", label: tk("Uploads") }, { value: "evaluation", label: tk("Evaluation") }, { value: "all", label: tk("All") },
];
export function SourceFilter({ value, onChange }: { value: Source; onChange: (s: Source) => void }) {
  const { t } = useApp();
  return (
    <div className="seg" role="group" aria-label={t("Source")}>
      {SOURCES.map((x) => <button key={x.value} aria-pressed={value === x.value} onClick={() => onChange(x.value)}>{t(x.label)}</button>)}
    </div>
  );
}
