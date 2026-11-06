import { useState } from "react";
import { api } from "../api";
import type { Stats } from "../types";
import { Empty, Err, Head, SourceFilter, type Source, can, day, dur, money, num, pct, tk, useApp, useLoad } from "../common";

/** First visit on an empty database: what this is, and two ways to see it work. */
function Welcome({ onLoaded }: { onLoaded: () => void }) {
  const { t, role, go, toast, refreshCounts } = useApp();
  const [busy, setBusy] = useState(false);
  const canLoad = can(role, "reviewer");
  async function load() {
    setBusy(true);
    try {
      const r = await api<{ ids: number[] }>("/samples/demo", { method: "POST" });
      toast(t("Loaded {n} sample invoices", { n: r.ids.length })); refreshCounts(); onLoaded();
    } catch (e) { toast((e as Error).message, "err"); } finally { setBusy(false); }
  }
  return (
    <div className="panel welcome">
      <h2>{t("Welcome to invoice-desk")}</h2>
      <p>{t("invoice-desk reads Saudi e-invoices, checks them against rules you control, and approves, rejects or sends each one to a person. Load a set of sample invoices to see it work, or try an AI model with your own key.")}</p>
      <div className="row wrap">
        <button className="btn primary" disabled={!canLoad || busy} onClick={load}>{busy ? t("Loading…") : t("Load sample invoices")}</button>
        <button className="btn" onClick={() => go("evaluation")}>{t("Try with your own AI key")}</button>
      </div>
      <p className="muted small">
        {canLoad ? t("20 invoices in English and Arabic, read by the built-in reader. No key needed.") : t("Sign in as reviewer or admin to load the samples.")}
      </p>
    </div>
  );
}

/** Round up to 2, 4 or 10 times a power of ten (never below 4), so the halfway mark is a whole number and one busy
 *  day reads as one busy day rather than a broken chart. */
export const niceMax = (n: number) => { const m = Math.max(4, n); const p = 10 ** Math.floor(Math.log10(m)); return [1, 2, 4, 10].map((k) => k * p).find((v) => v >= m && v % 2 === 0)!; };

/** Invoices per day for the last 14 days: bars on a baseline, a faint tick for an empty day, the scale and the busiest
 *  day labelled. A list of the days with their counts is there for screen readers. */
function DayChart({ series }: { series: Stats["series"] }) {
  const { t } = useApp();
  const top = niceMax(Math.max(0, ...series.map((d) => d.count)));
  const peak = Math.max(0, ...series.map((d) => d.count));
  const peakAt = series.findIndex((d) => d.count === peak);
  return (
    <figure className="daychart">
      <div className="dc-plot" aria-hidden="true">
        <span className="dc-tick top num">{num(top)}</span>
        <span className="dc-tick mid num">{num(top / 2)}</span>
        {series.map((d, i) => (
          <div key={d.day} className={`dc-col${d.count ? "" : " zero"}`} title={`${day(d.day)}: ${num(d.count)}`}>
            {d.count > 0 && <div className="dc-bar" style={{ height: `${(d.count / top) * 100}%` }}>{i === peakAt && <span className="dc-val num">{num(d.count)}</span>}</div>}
          </div>
        ))}
      </div>
      <div className="dc-axis small muted"><span>{day(series[0].day)}</span><span>{day(series[series.length - 1].day)}</span></div>
      <figcaption className="sr-only">{t("Invoices received in the last 14 days")}
        <ul>{series.map((d) => <li key={d.day}>{day(d.day)}: {num(d.count)}</li>)}</ul>
      </figcaption>
    </figure>
  );
}

export default function Dashboard() {
  const { t } = useApp();
  const [source, setSource] = useState<Source>("upload");
  const { data: s, error, reload } = useLoad(() => api<Stats>(`/stats?source=${source}`), [source],
    (d) => d.by_status.queued + d.by_status.processing > 0);
  const head = (
    <Head title={t("Dashboard")} sub={t("Every invoice ends up in one of these states. Most should clear without a person touching them.")}>
      <SourceFilter value={source} onChange={setSource} />
    </Head>
  );
  if (!s) return <>{head}<Err msg={error} /></>;
  const b = s.by_status;
  const parts = [
    { k: "a", n: b.approved, label: tk("Approved automatically") }, { k: "h", n: b.approved_human, label: tk("Approved by a person") },
    { k: "r", n: b.needs_review, label: tk("Waiting for review") }, { k: "x", n: b.rejected + b.rejected_human + b.failed, label: tk("Rejected or failed") },
  ];
  const sum = parts.reduce((a, p) => a + p.n, 0);
  const maxFail = Math.max(1, ...s.top_failing.map((f) => f.count));
  const maxReason = Math.max(1, ...s.top_rejections.map((f) => f.count));
  return (
    <>
      {head}
      <Err msg={error} />
      {s.uploads === 0 && source === "upload" ? <Welcome onLoaded={reload} /> : s.total === 0 ? (
        <div className="panel"><Empty title={source === "evaluation" ? t("No evaluation runs yet") : t("No invoices yet")}
          hint={source === "evaluation" ? t("Run an evaluation and its invoices appear here, apart from your uploads.") : t("Upload your own, or load a few of the built-in samples to see the pipeline work.")} /></div>
      ) : (
        <div className="col dash">
          <section className="panel hero">
            <div className="hero-top">
              <div className="headline"><b className="num">{pct(s.auto_approve_rate)}</b><span>{t("cleared without a person")}</span></div>
              <div className="kpis">
                <div className="kpi"><b className="num">{num(s.total)}</b><span>{t("invoices received")}</span></div>
                <div className="kpi"><b className="num">{num(s.review_queue)}</b><span>{t("waiting in the review queue")}</span></div>
                <div className="kpi"><b className="num">{num(s.human_corrected)}</b><span>{t("fixed by a reviewer")}</span></div>
                <div className="kpi"><b className="num">{dur(s.avg_time_to_review_s)}</b><span>{t("average time to decide")}</span></div>
              </div>
            </div>
            <div className="strip" role="img" aria-label={parts.map((p) => `${t(p.label)}: ${num(p.n)}`).join("، ")}>
              {parts.filter((p) => p.n).map((p) => <div key={p.k} className={p.k} style={{ flexGrow: p.n }}>{p.n / sum > 0.07 ? num(p.n) : ""}</div>)}
            </div>
            <div className="legend">
              {parts.map((p) => <span key={p.k}><i className={p.k} />{t(p.label)} <b className="num">{num(p.n)}</b></span>)}
            </div>
          </section>
          <div className="grid g2">
            <div className="panel">
              <h2>{t("Rules that fail most")}</h2>
              {s.top_failing.length === 0 ? <p className="muted">{t("Nothing has failed a rule yet.")}</p> :
                s.top_failing.map((f) => <div className="hbar" key={f.rule}><span title={t(f.rule)}>{t(f.rule)}</span><span className="t"><i style={{ width: `${(f.count / maxFail) * 100}%` }} /></span><b className="num">{num(f.count)}</b></div>)}
            </div>
            <div className="panel">
              <h2>{t("Top rejection reasons")}</h2>
              {s.top_rejections.length === 0 ? <p className="muted">{t("Nothing has been rejected yet.")}</p> :
                s.top_rejections.map((f) => <div className="hbar bad" key={f.reason}><span title={t(f.reason)}>{t(f.reason)}</span><span className="t"><i style={{ width: `${(f.count / maxReason) * 100}%` }} /></span><b className="num">{num(f.count)}</b></div>)}
            </div>
          </div>
          <div className="grid g2">
            <div className="panel">
              <h2>{t("Invoices per day")}</h2>
              <DayChart series={s.series} />
            </div>
            <div className="panel">
              <h2>{t("AI model usage")}</h2>
              {s.ai_runs === 0 ? <p className="muted">{t("No invoices have used an AI model yet. The rest ran on the built-in rules, which cost nothing.")}</p> : (
                <div className="facts" style={{ marginTop: 0 }}>
                  <div className="fact"><b>{num(s.ai_runs)}</b><span>{t("invoices read by an AI model")}</span></div>
                  <div className="fact"><b>{num(s.tokens_in + s.tokens_out)}</b><span>{t("tokens used")}</span></div>
                  <div className="fact"><b>{s.avg_extract_ms == null ? "–" : t("{ms} ms", { ms: s.avg_extract_ms })}</b><span>{t("average read time")}</span></div>
                  <div className="fact"><b>{s.cost == null ? "–" : <bdi dir="ltr">{money(s.cost)}</bdi>}</b><span>{s.cost == null ? t("add token prices in Settings to see cost") : t("estimated cost (USD)")}</span></div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
