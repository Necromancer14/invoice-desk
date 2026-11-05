import { api } from "../api";
import type { Stats } from "../types";
import { Empty, Err, Head, day, dur, money, num, pct, tk, useApp, useLoad } from "../common";

export default function Dashboard() {
  const { t, go } = useApp();
  const { data: s, error } = useLoad(() => api<Stats>("/stats"), [], (d) => d.by_status.queued + d.by_status.processing > 0);
  if (!s) return <><Head title={t("Dashboard")} /><Err msg={error} /></>;
  const b = s.by_status;
  const parts = [
    { k: "a", n: b.approved, label: tk("Approved automatically") }, { k: "h", n: b.approved_human, label: tk("Approved by a person") },
    { k: "r", n: b.needs_review, label: tk("Waiting for review") }, { k: "x", n: b.rejected + b.rejected_human + b.failed, label: tk("Rejected or failed") },
  ];
  const sum = parts.reduce((a, p) => a + p.n, 0);
  const max = Math.max(1, ...s.series.map((d) => d.count));
  const maxFail = Math.max(1, ...s.top_failing.map((f) => f.count));
  return (
    <>
      <Head title={t("Dashboard")} sub={t("Every invoice ends up in one of these states. Most should clear without a person touching them.")} />
      <Err msg={error} />
      {s.total === 0 ? (
        <div className="panel"><Empty title={t("No invoices yet")} hint={t("Upload your own, or load a few of the built-in samples to see the pipeline work.")}>
          <p style={{ marginTop: 12 }}><button className="btn primary" onClick={() => go("intake")}>{t("Upload invoices")}</button></p></Empty></div>
      ) : (
        <div className="col" style={{ gap: 18 }}>
          <div className="panel">
            <div className="strip" role="img" aria-label={parts.map((p) => `${t(p.label)}: ${num(p.n)}`).join("، ")}>
              {parts.filter((p) => p.n).map((p) => <div key={p.k} className={p.k} style={{ flexGrow: p.n }}>{p.n / sum > 0.07 ? num(p.n) : ""}</div>)}
            </div>
            <div className="legend">
              {parts.map((p) => <span key={p.k}><i className={p.k} style={{ background: p.k === "a" ? "var(--accent)" : p.k === "h" ? "var(--accent-soft)" : p.k === "r" ? "var(--amber)" : "var(--red)", border: "1px solid var(--line-strong)" }} />{t(p.label)} ({num(p.n)})</span>)}
            </div>
            <div className="facts">
              <div className="fact"><b>{num(s.total)}</b><span>{t("invoices received")}</span></div>
              <div className="fact"><b>{pct(s.auto_approve_rate)}</b><span>{t("cleared without a person")}</span></div>
              <div className="fact"><b>{num(s.review_queue)}</b><span>{t("waiting in the review queue")}</span></div>
              <div className="fact"><b>{num(s.human_corrected)}</b><span>{t("fixed by a reviewer")}</span></div>
              <div className="fact"><b>{dur(s.avg_time_to_review_s)}</b><span>{t("average time to decide")}</span></div>
            </div>
          </div>
          <div className="grid g2">
            <div className="panel">
              <h2>{t("Invoices per day")}</h2>
              <div className="bars" role="img" aria-label={t("Invoices received in the last 14 days")}>
                {s.series.map((d) => <div key={d.day} title={`${day(d.day)}: ${num(d.count)}`} style={{ height: `${(d.count / max) * 100}%` }} />)}
              </div>
              <div className="row muted small" style={{ justifyContent: "space-between", marginTop: 6 }}><span>{day(s.series[0].day)}</span><span>{day(s.series[s.series.length - 1].day)}</span></div>
            </div>
            <div className="panel">
              <h2>{t("Rules that fail most")}</h2>
              {s.top_failing.length === 0 ? <p className="muted">{t("Nothing has failed a rule yet.")}</p> :
                s.top_failing.map((f) => <div className="hbar" key={f.rule}><span title={t(f.rule)}>{t(f.rule)}</span><span className="t"><i style={{ width: `${(f.count / maxFail) * 100}%` }} /></span><b className="num">{num(f.count)}</b></div>)}
            </div>
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
      )}
    </>
  );
}
