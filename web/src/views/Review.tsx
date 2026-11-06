import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type { QueueItem, RunDetail } from "../types";
import { Empty, Err, Head, ago, money, useApp, useLoad } from "../common";
import { Document, Evidence, ReviewForm, RunHeader } from "./RunDetail";

const typing = (e: KeyboardEvent) => {
  const el = e.target as HTMLElement;
  return el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable;
};

const Arrow = ({ d }: { d: string }) => (
  <svg className="flip-rtl" width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={d} /></svg>
);
const PREV = "M10 3L5 8l5 5";
const NEXT = "M6 3l5 5-5 5";

/** Review queue: the waiting invoices on the left, the selected one on the right. The URL is #/review/<id>. */
export default function Review({ openId }: { openId?: number }) {
  const { t, go, setQueueCount } = useApp();
  const queue = useLoad(() => api<QueueItem[]>("/review/queue"), []);
  const [items, setItems] = useState<QueueItem[] | null>(null);
  const [q, setQ] = useState("");
  useEffect(() => { if (queue.data) setItems(queue.data); }, [queue.data]);
  useEffect(() => { if (items) setQueueCount(items.length); }, [items, setQueueCount]);
  // New uploads land in the queue while someone is reviewing, so refresh it now and then.
  useEffect(() => { const id = setInterval(queue.reload, 10000); return () => clearInterval(id); }, [queue.reload]);

  const shown = useMemo(() => {
    const s = q.trim().toLowerCase();
    if (!items || !s) return items ?? [];
    return items.filter((i) => [i.seller, i.invoice_number, i.filename, String(i.id)].some((v) => v?.toLowerCase().includes(s)));
  }, [items, q]);

  // The URL is the source of truth, but the hashchange event arrives a moment after we set it,
  // so the choice is mirrored in state to avoid a render that briefly falls back to the first item.
  const [sel, setSel] = useState<number | undefined>(openId);
  useEffect(() => setSel(openId), [openId]);
  const inQueue = sel != null && !!items?.some((i) => i.id === sel);
  const selected = inQueue ? sel : shown[0]?.id;
  const pos = shown.findIndex((i) => i.id === selected);
  const select = (id: number | undefined) => { setSel(id); if (id == null) go("review"); else go("review", String(id)); };
  const step = (d: number) => { const n = shown[pos + d]; if (n) select(n.id); };

  // Load the selected run. Answers for an earlier selection are dropped so a slow reply cannot overwrite a newer one.
  const [run, setRun] = useState<RunDetail | null>(null);
  const [detailErr, setDetailErr] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    setDetailErr(null);
    if (selected == null) { setRun(null); return; }
    api<RunDetail>(`/runs/${selected}`).then((r) => { if (live) setRun(r); }).catch((e) => { if (live) setDetailErr((e as Error).message); });
    return () => { live = false; };
  }, [selected]);

  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (typing(e) || e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.key === "j") { e.preventDefault(); step(1); }
      if (e.key === "k") { e.preventDefault(); step(-1); }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  });

  /** After a decision: drop the item and move to the one that took its place, or the previous one if it was last. */
  function decided(id: number) {
    const list = items ?? [];
    const visible = shown.filter((i) => i.id !== id);
    const at = shown.findIndex((i) => i.id === id);
    const next = visible[Math.min(at, visible.length - 1)];
    setItems(list.filter((i) => i.id !== id));
    select(next?.id);
    queue.reload();
  }

  const loading = queue.loading && !items;
  const empty = !loading && items !== null && items.length === 0;
  const current = run && run.id === selected ? run : null;

  return (
    <>
      <Head title={t("Review queue")} sub={t("Invoices the rules could not settle on their own. Check the original, fix anything the reader got wrong, then decide.")}>
        <span className="muted small rq-keys">{t("Shortcuts")}: <kbd>j</kbd> {t("next")} · <kbd>k</kbd> {t("previous")} · <kbd>a</kbd> {t("approve")} · <kbd>r</kbd> {t("jump to note")}</span>
      </Head>
      <Err msg={queue.error} />
      {sel != null && items && !inQueue && (
        <div className="notice warn" style={{ marginBottom: 14 }}>
          {t("Invoice #{id} is no longer waiting for review.", { id: sel })}{" "}
          <button className="btn small" onClick={() => go("runs", String(sel))}>{t("Open it in Runs")}</button>
        </div>
      )}
      {empty && (
        <div className="panel"><Empty title={t("The queue is clear")} hint={t("Nothing is waiting for a person right now.")}>
          <p style={{ marginTop: 12 }}><button className="btn" onClick={() => go("intake")}>{t("Upload more invoices")}</button></p></Empty></div>
      )}
      {items && items.length > 0 && (
        <div className={`rq ${sel != null ? "show-detail" : ""}`}>
          <section className="panel rq-list" aria-label={t("Invoices waiting for review")}>
            <input type="search" placeholder={t("Search the queue")} aria-label={t("Search the queue")} value={q} onChange={(e) => setQ(e.target.value)} />
            {/* A plain list of buttons: Tab moves through it, j and k step through the queue. aria-current marks the open one. */}
            <ul className="rq-items" aria-label={t("Invoices waiting for review")}>
              {shown.map((i) => (
                <li key={i.id}><button aria-current={i.id === selected ? "true" : undefined} className="rq-item" onClick={() => select(i.id)}>
                  <span className="rq-top"><b className="cell-text" dir="auto">{i.seller || i.filename}</b><span className="num"><bdi dir="ltr">{money(i.total, i.currency)}</bdi></span></span>
                  <span className="rq-sub muted small">
                    <bdi dir="ltr">{i.invoice_number || `#${i.id}`}</bdi>
                    <span className="rq-fails">{t("{n} checks failed", { n: i.failed_checks })}</span>
                    {i.high_risk && <span className="pill s-rejected risk-pill">{t("High risk")}</span>}
                    <span className="right">{ago(i.created_at)}</span>
                  </span>
                </button></li>
              ))}
              {shown.length === 0 && <li className="muted small" style={{ padding: 10 }}>{t("Nothing matches the search.")}</li>}
            </ul>
          </section>

          <section className="rq-detail col" style={{ gap: 14 }} aria-live="polite">
            <div className="row wrap rq-nav">
              <button className="btn small rq-back" onClick={() => select(undefined)}><Arrow d={PREV} />{t("Back to the list")}</button>
              <button className="btn small" disabled={pos <= 0} onClick={() => step(-1)}><Arrow d={PREV} />{t("Previous")}</button>
              <button className="btn small" disabled={pos < 0 || pos >= shown.length - 1} onClick={() => step(1)}>{t("Next")}<Arrow d={NEXT} /></button>
              {pos >= 0 && <span className="muted small">{t("{n} of {total}", { n: pos + 1, total: shown.length })}</span>}
            </div>
            <Err msg={detailErr} />
            {current && (
              <>
                <RunHeader run={current} />
                <div className="split">
                  <Document run={current} />
                  <div className="panel"><ReviewForm run={current} onDone={() => decided(current.id)} /></div>
                </div>
                <div className="panel"><h2>{t("Why this needs a person")}</h2><Evidence run={current} onChange={setRun} /></div>
              </>
            )}
          </section>
        </div>
      )}
    </>
  );
}
