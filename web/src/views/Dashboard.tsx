import { api } from "../api";
import type { Stats } from "../types";
import { Empty, Err, Head, dur, money, pct, useApp, useLoad } from "../common";

export default function Dashboard() {
  const { t, go } = useApp();
  const { data: s, error } = useLoad(() => api<Stats>("/stats"), [], (d) => d.by_status.queued + d.by_status.processing > 0);
  if (!s) return <><Head title={t("Dashboard")} /><Err msg={error} /></>;
  const b = s.by_status;
  const parts = [
    { k: "a", n: b.approved, label: "Approved automatically" }, { k: "h", n: b.approved_human, label: "Approved by a person" },
    { k: "r", n: b.needs_review, label: "Waiting for review" }, { k: "x", n: b.rejected + b.rejected_human + b.failed, label: "Rejected or failed" },
  ];
  const sum = parts.reduce((a, p) => a + p.n, 0);
  const max = Math.max(1, ...s.series.map((d) => d.count));
  const maxFail = Math.max(1, ...s.top_failing.map((f) => f.count));
  return (
    <>
      <Head title={t("Dashboard")} sub="Every invoice ends up in one of these states. Most should clear without a person touching them." />
      <Err msg={error} />
      {s.total === 0 ? (
        <div className="panel"><Empty title="No invoices yet" hint="Upload your own, or load a few of the built-in samples to see the pipeline work.">
          <p style={{ marginTop: 12 }}><button className="btn primary" onClick={() => go("intake")}>Upload invoices</button></p></Empty></div>
      ) : (
        <div className="col" style={{ gap: 18 }}>
          <div className="panel">
            <div className="strip" role="img" aria-label={parts.map((p) => `${p.label}: ${p.n}`).join(", ")}>
              {parts.filter((p) => p.n).map((p) => <div key={p.k} className={p.k} style={{ flexGrow: p.n }}>{p.n / sum > 0.07 ? p.n : ""}</div>)}
            </div>
            <div className="legend">
              {parts.map((p) => <span key={p.k}><i className={p.k} style={{ background: p.k === "a" ? "var(--accent)" : p.k === "h" ? "var(--accent-soft)" : p.k === "r" ? "var(--amber)" : "var(--red)", border: "1px solid var(--line-strong)" }} />{p.label} ({p.n})</span>)}
            </div>
            <div className="facts">
              <div className="fact"><b>{s.total}</b><span>invoices received</span></div>
              <div className="fact"><b>{pct(s.auto_approve_rate)}</b><span>cleared without a person</span></div>
              <div className="fact"><b>{s.review_queue}</b><span>waiting in the review queue</span></div>
              <div className="fact"><b>{s.human_corrected}</b><span>fixed by a reviewer</span></div>
              <div className="fact"><b>{dur(s.avg_time_to_review_s)}</b><span>average time to decide</span></div>
            </div>
          </div>
          <div className="grid g2">
            <div className="panel">
              <h2>Invoices per day</h2>
              <div className="bars" role="img" aria-label="Invoices received in the last 14 days">
                {s.series.map((d) => <div key={d.day} title={`${d.day}: ${d.count}`} style={{ height: `${(d.count / max) * 100}%` }} />)}
              </div>
              <div className="row muted small" style={{ justifyContent: "space-between", marginTop: 6 }}><span>{s.series[0].day}</span><span>{s.series[s.series.length - 1].day}</span></div>
            </div>
            <div className="panel">
              <h2>Rules that fail most</h2>
              {s.top_failing.length === 0 ? <p className="muted">Nothing has failed a rule yet.</p> :
                s.top_failing.map((f) => <div className="hbar" key={f.rule}><span title={f.rule}>{f.rule}</span><span className="t"><i style={{ width: `${(f.count / maxFail) * 100}%` }} /></span><b className="num">{f.count}</b></div>)}
            </div>
          </div>
          <div className="panel">
            <h2>AI model usage</h2>
            {s.ai_runs === 0 ? <p className="muted">No invoices have used an AI model yet. The rest ran on the built-in rules, which cost nothing.</p> : (
              <div className="facts" style={{ marginTop: 0 }}>
                <div className="fact"><b>{s.ai_runs}</b><span>invoices read by an AI model</span></div>
                <div className="fact"><b>{(s.tokens_in + s.tokens_out).toLocaleString()}</b><span>tokens used</span></div>
                <div className="fact"><b>{s.avg_extract_ms ?? "–"} ms</b><span>average read time</span></div>
                <div className="fact"><b>{s.cost == null ? "–" : money(s.cost)}</b><span>{s.cost == null ? "add token prices in Settings to see cost" : "estimated cost (USD)"}</span></div>
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}
