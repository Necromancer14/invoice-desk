import { useState, type ReactNode } from "react";
import { api } from "../api";
import type { Activity, Period, PeriodDay, Stats } from "../types";
import {
  Empty, Err, Head, SourceFilter, type Source, ago, can, compactMoney, day, dur, isRtl, longDay, money, num, pct, tk, useApp, useLoad,
} from "../common";

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
        {canLoad ? t("Sample invoices in English and Arabic, dated over the last 30 days and read by the built-in reader. No key needed.") : t("Sign in as reviewer or admin to load the samples.")}
      </p>
    </div>
  );
}

/** Round up to 2, 4 or 10 times a power of ten (never below 4), so the halfway mark is a whole number and one busy
 *  day reads as one busy day rather than a broken chart. */
export const niceMax = (n: number) => { const m = Math.max(4, n); const p = 10 ** Math.floor(Math.log10(m)); return [1, 2, 4, 10].map((k) => k * p).find((v) => v >= m && v % 2 === 0)!; };

const PERIODS = [7, 30, 90] as const;
type Days = (typeof PERIODS)[number];
const PERIOD_LABEL: Record<Days, string> = { 7: tk("7 days"), 30: tk("30 days"), 90: tk("90 days") };

/** The outcome series, bottom to top, in the status colours. */
const SERIES = [
  { k: "auto", cls: "a", label: tk("Approved automatically") }, { k: "person", cls: "h", label: tk("Approved by a person") },
  { k: "review", cls: "r", label: tk("Waiting for review") }, { k: "rejected", cls: "x", label: tk("Rejected or failed") },
] as const;
type SeriesKey = (typeof SERIES)[number]["k"];

function savedPeriod(): Days {
  try { const v = Number(localStorage.getItem("id-period")); return (PERIODS as readonly number[]).includes(v) ? (v as Days) : 7; } catch { return 7; }
}

/** Wrap the first appearance of `part` in `text` with `wrap`, so a translated sentence can stress its number. */
function stress(text: string, part: string, wrap: (s: string) => ReactNode): ReactNode {
  const at = part ? text.indexOf(part) : -1;
  if (at < 0) return text;
  return <>{text.slice(0, at)}{wrap(part)}{text.slice(at + part.length)}</>;
}

function greetingKey(h: number) {
  return h < 5 ? tk("Good evening, {name}") : h < 12 ? tk("Good morning, {name}") : h < 17 ? tk("Good afternoon, {name}") : tk("Good evening, {name}");
}

/** Greeting and one sentence about today: what waits for a person, what is high risk, what falls due this week. */
function Greeting({ p, children }: { p: Period; children: ReactNode }) {
  const { t, name, go, role } = useApp();
  const parts: ReactNode[] = [];
  const n = p.waiting_count;
  if (n) {
    const text = t("{n} invoices need a person", { n });
    parts.push(<button key="w" className="linkish" onClick={() => go("review")}>{stress(text, num(n), (s) => <b className="num">{s}</b>)}</button>);
    if (p.high_risk) {
      const r = t("{n} marked high risk", { n: p.high_risk });
      parts.push(<button key="r" className="linkish risk" onClick={() => go("review")}>{stress(r, num(p.high_risk), (s) => <b className="num">{s}</b>)}</button>);
    }
  } else {
    parts.push(<span key="w">{t("Nothing is waiting for a person.")}</span>);
  }
  if (p.due_soon.value > 0) {
    const amount = money(p.due_soon.value, "SAR");
    parts.push(<span key="d">{stress(t("{amount} approved and due in the next 7 days", { amount }), amount, (s) => <b><bdi dir="ltr" className="num">{s}</bdi></b>)}</span>);
  }
  return (
    <div className="page-head greet">
      <div className="grow">
        <h1>{t(greetingKey(new Date().getHours()), { name })}</h1>
        <p className="greet-line"><span>{longDay()}</span>{parts.map((x, i) => <span key={i} className="greet-part">{x}</span>)}</p>
      </div>
      <div className="row wrap greet-actions">
        {children}
        {can(role, "reviewer") && <button className="btn primary" onClick={() => go("intake")}>{t("Upload invoices")}</button>}
      </div>
    </div>
  );
}

/** A small trend line under a figure. Decorative: the figure and its change say the same in words. */
function Spark({ values }: { values: number[] }) {
  if (values.length < 2) return null;
  const top = Math.max(1, ...values);
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * 100},${26 - (v / top) * 24}`);
  return (
    <svg className="spark" viewBox="0 0 100 28" preserveAspectRatio="none" aria-hidden="true" style={isRtl() ? { transform: "scaleX(-1)" } : undefined}>
      <polygon points={`0,28 ${pts.join(" ")} 100,28`} className="spark-area" />
      <polyline points={pts.join(" ")} className="spark-line" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

/** Change against the window before. `good`: which direction is good news, or "none" when neither is. */
function Delta({ now, before, good, points }: { now: number | null; before: number | null; good: "up" | "down" | "none"; points?: boolean }) {
  const { t } = useApp();
  if (now == null || before == null || (!points && before === 0)) return <span className="delta none">{t("no earlier figures")}</span>;
  const diff = points ? (now - before) * 100 : (now - before) / before;
  if (Math.abs(diff) < (points ? 0.5 : 0.005)) return <span className="delta flat">{t("no change")}</span>;
  const up = diff > 0;
  const tone = good === "none" ? "neutral" : (up === (good === "up")) ? "good" : "bad";
  const size = points ? t("{n} pts", { n: Math.round(Math.abs(diff)) }) : pct(Math.abs(diff));
  return (
    <span className="delta-wrap">
      <span className={`delta ${tone}`}>
        <span aria-hidden="true">{up ? "↑" : "↓"}</span>
        <span className="sr-only">{up ? t("up") : t("down")}</span> <bdi className="num">{size}</bdi>
      </span>
      <span className="muted small">{t("vs the period before")}</span>
    </span>
  );
}

function Tile({ label, value, title, delta, spark, foot }: { label: string; value: ReactNode; title?: string; delta: ReactNode; spark: number[]; foot?: ReactNode }) {
  return (
    <div className="panel tile">
      <span className="tile-label">{label}</span>
      <b className="tile-value num" title={title}>{value}</b>
      <div className="tile-foot">{delta}</div>
      {foot && <span className="muted small tile-note">{foot}</span>}
      <Spark values={spark} />
    </div>
  );
}

/** Invoices per day, stacked by outcome, as areas on a baseline. The legend switches a series off and on; a column
 *  under the pointer shows that day's counts. A list of the days is there for screen readers. */
function OutcomeChart({ series }: { series: PeriodDay[] }) {
  const { t } = useApp();
  const [off, setOff] = useState<Set<SeriesKey>>(new Set());
  const [hover, setHover] = useState<number | null>(null);
  const shown = SERIES.filter((s) => !off.has(s.k));
  const totals = series.map((d) => shown.reduce((a, s) => a + d[s.k], 0));
  const top = niceMax(Math.max(0, ...totals));
  const W = 1000, H = 200, n = series.length;
  const x = (i: number) => (n === 1 ? W / 2 : (i / (n - 1)) * W);
  const y = (v: number) => H - (v / top) * H;
  // Each edge is a run of cubic curves whose control points sit halfway across at the two end heights: smooth, never
  // overshooting a day's value, and since every edge uses the same x steps a layer never crosses the one below it.
  const edge = (vals: number[], rev: boolean) => {
    const pts = vals.map((v, i) => [x(i), y(v)] as const);
    if (rev) pts.reverse();
    return pts.map(([px, py], i) => {
      if (i === 0) return `${px},${py}`;
      const [qx, qy] = pts[i - 1], mx = (qx + px) / 2;
      return `C${mx},${qy} ${mx},${py} ${px},${py}`;
    }).join(" ");
  };
  const layers: { k: SeriesKey; cls: string; d: string }[] = [];
  const base = series.map(() => 0);
  for (const s of shown) {
    const lower = [...base];
    series.forEach((d, i) => { base[i] += d[s.k]; });
    layers.push({ k: s.k, cls: s.cls, d: `M${edge(base, false)} L${edge(lower, true)}Z` });
  }
  const h = hover == null ? null : series[hover];
  return (
    <figure className="oc">
      <div className="oc-legend" role="group" aria-label={t("Show or hide a series")}>
        {SERIES.map((s) => (
          <button key={s.k} className="oc-key" aria-pressed={!off.has(s.k)}
            onClick={() => setOff((o) => { const c = new Set(o); if (c.has(s.k)) c.delete(s.k); else if (shown.length > 1) c.add(s.k); return c; })}>
            <i className={s.cls} />{t(s.label)}
          </button>
        ))}
      </div>
      <div className="oc-plot" aria-hidden="true">
        <span className="dc-tick top num">{num(top)}</span>
        <span className="dc-tick mid num">{num(top / 2)}</span>
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={isRtl() ? { transform: "scaleX(-1)" } : undefined}>
          <line x1="0" x2={W} y1={H / 2} y2={H / 2} className="oc-grid" vectorEffect="non-scaling-stroke" />
          {layers.map((l) => <path key={l.k} d={l.d} className={`oc-area ${l.cls}`} />)}
          {hover != null && <line x1={x(hover)} x2={x(hover)} y1="0" y2={H} className="oc-cursor" vectorEffect="non-scaling-stroke" />}
        </svg>
        <div className="oc-cols" onMouseLeave={() => setHover(null)}>
          {series.map((d, i) => <div key={d.day} onMouseEnter={() => setHover(i)} />)}
        </div>
        {h && (
          <div className={`oc-tip${hover! > n / 2 ? " flip" : ""}`} style={{ insetInlineStart: `${(hover! / Math.max(1, n - 1)) * 100}%` }}>
            <b>{day(h.day)}</b>
            {SERIES.map((s) => <span key={s.k}><i className={s.cls} />{t(s.label)} <b className="num">{num(h[s.k])}</b></span>)}
            {h.value > 0 && <span className="muted"><bdi dir="ltr" className="num">{money(h.value, "SAR")}</bdi></span>}
          </div>
        )}
      </div>
      <div className="dc-axis small muted"><span>{day(series[0].day)}</span><span>{day(series[series.length - 1].day)}</span></div>
      <figcaption className="sr-only">{t("Invoices received per day, by outcome")}
        <ul>{series.map((d) => <li key={d.day}>{day(d.day)}: {SERIES.map((s) => `${t(s.label)} ${num(d[s.k])}`).join(", ")}</li>)}</ul>
      </figcaption>
    </figure>
  );
}

/** The invoices that have waited longest for a person, with a way straight in. */
function Waiting({ p }: { p: Period }) {
  const { t, go } = useApp();
  return (
    <div className="panel">
      <div className="row panel-head"><h2 className="grow">{t("Waiting longest")}</h2>
        {p.waiting_count > 0 && <button className="btn ghost small" onClick={() => go("review")}>{t("Open the review queue")}</button>}</div>
      {p.waiting.length === 0 ? <p className="muted">{t("Nothing is waiting. The review queue is clear.")}</p> : (
        <ul className="wl">
          {p.waiting.map((w) => (
            <li key={w.id}>
              <div className="grow wl-main">
                <span className="wl-name" dir="auto">{w.seller || w.filename}</span>
                <span className="muted small"><bdi dir="ltr">{w.invoice_number || `#${w.id}`}</bdi> · {ago(w.created_at)}
                  {w.high_risk && <span className="pill risk-pill">{t("High risk")}</span>}</span>
              </div>
              <b className="num wl-amt"><bdi dir="ltr">{money(w.total, w.currency)}</bdi></b>
              <button className="btn small" onClick={() => go("review", String(w.id))} aria-label={t("Open {name}", { name: w.seller || w.filename })}>{t("Open")}</button>
            </li>
          ))}
        </ul>
      )}
      {p.waiting_count > 0 && (
        <p className="muted small wl-foot">{t("{n} waiting in all", { n: p.waiting_count })}
          {p.waiting_value > 0 && <> · <bdi dir="ltr" className="num">{money(p.waiting_value, "SAR")}</bdi></>}</p>
      )}
    </div>
  );
}

const ACTION_TEXT: Record<string, string> = {
  "review.approve": tk("{actor} approved {what}"), "review.reject": tk("{actor} rejected {what}"),
  "run.reprocess": tk("{actor} had invoice {what} read again"), "vendor.link": tk("{actor} linked an invoice to a vendor"),
  "vendor.create": tk("{actor} added a vendor"), "vendor.update": tk("{actor} updated a vendor"), "vendor.delete": tk("{actor} removed a vendor"),
  "vendor.import": tk("{actor} imported vendors"), "po.import": tk("{actor} imported purchase orders"), "po.delete": tk("{actor} removed a purchase order"),
  "rule.update": tk("{actor} changed a rule"), "rule.delete": tk("{actor} deleted a rule"), "rule.reorder": tk("{actor} reordered the rules"),
  "rule.rollback": tk("{actor} restored an earlier rule version"), "settings.update": tk("{actor} changed the settings"),
  "demo.samples": tk("{actor} loaded the sample invoices"), "demo.reset": tk("{actor} reset the demo"),
};

/** What people did lately, in sentences. */
function Feed({ rows }: { rows: Activity[] }) {
  const { t, go } = useApp();
  return (
    <div className="panel">
      <div className="row panel-head"><h2 className="grow">{t("Recent activity")}</h2>
        <button className="btn ghost small" onClick={() => go("audit")}>{t("Audit log")}</button></div>
      {rows.length === 0 ? <p className="muted">{t("Nobody has done anything yet.")}</p> : (
        <ul className="feed">
          {rows.map((a) => {
            const actor = a.actor === "system" ? t("The desk") : a.actor;
            const what = a.run ? (a.run.seller_name || a.run.invoice_number || a.run.filename) : `#${a.target}`;
            const text = t(ACTION_TEXT[a.action] ?? a.action, { actor: "⁨" + actor + "⁩", what: "⁨" + what + "⁩" });
            const open = a.target && /^\d+$/.test(a.target) && (a.action.startsWith("review.") || a.action === "run.reprocess");
            return (
              <li key={a.id}>
                <span className="avatar" aria-hidden="true">{actor.slice(0, 2).toUpperCase()}</span>
                <div className="grow">
                  {open ? <button className="linkish" onClick={() => go("runs", a.target)}>{text}</button> : <span>{text}</span>}
                  <span className="muted small feed-meta">{ago(a.ts)}
                    {a.run?.total != null && <> · <bdi dir="ltr" className="num">{money(a.run.total, a.run.currency)}</bdi></>}</span>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

export default function Dashboard() {
  const { t, go } = useApp();
  const [source, setSource] = useState<Source>("upload");
  const [days, setDaysState] = useState<Days>(savedPeriod);
  const setDays = (d: Days) => { setDaysState(d); try { localStorage.setItem("id-period", String(d)); } catch { /* private window */ } };
  const { data, error, reload } = useLoad(
    () => Promise.all([api<Stats>(`/stats?source=${source}&days=${days}`), api<Activity[]>("/activity?limit=8")]),
    [source, days], ([d]) => d.by_status.queued + d.by_status.processing > 0);
  const controls = (
    <>
      <div className="seg" role="group" aria-label={t("Period")}>
        {PERIODS.map((d) => <button key={d} aria-pressed={days === d} onClick={() => setDays(d)}>{t(PERIOD_LABEL[d])}</button>)}
      </div>
      <SourceFilter value={source} onChange={setSource} />
    </>
  );
  const plain = <Head title={t("Dashboard")} sub={t("Every invoice ends up in one of these states. Most should clear without a person touching them.")}>{controls}</Head>;
  if (!data) return <>{plain}<Err msg={error} /></>;
  const [s, activity] = data;
  const p = s.period!;
  if (s.uploads === 0 && source === "upload") return <>{plain}<Err msg={error} /><Welcome onLoaded={reload} /></>;
  if (s.total === 0) {
    return (
      <>{plain}<Err msg={error} />
        <div className="panel"><Empty title={source === "evaluation" ? t("No evaluation runs yet") : t("No invoices yet")}
          hint={source === "evaluation" ? t("Run an evaluation and its invoices appear here, apart from your uploads.") : t("Upload your own, or load a few of the built-in samples to see the pipeline work.")} /></div>
      </>
    );
  }
  const c = p.current, b = p.previous;
  const busy = s.by_status.queued + s.by_status.processing;
  const parts = [
    { k: "a", n: c.approved, label: SERIES[0].label }, { k: "h", n: c.approved_human, label: SERIES[1].label },
    { k: "r", n: c.waiting, label: SERIES[2].label }, { k: "x", n: c.rejected, label: SERIES[3].label },
  ];
  const sum = parts.reduce((a, x) => a + x.n, 0);
  const maxFail = Math.max(1, ...p.top_failing.map((f) => f.count));
  const maxReason = Math.max(1, ...p.top_rejections.map((f) => f.count));
  const daily = (f: (d: PeriodDay) => number) => p.series.map(f);
  const sar = (v: number) => <bdi dir="ltr">{compactMoney(v, "SAR")}</bdi>;
  const otherFoot = c.other_currency ? t("plus {n} invoices in other currencies", { n: c.other_currency }) : undefined;
  return (
    <>
      <Greeting p={p}>{controls}</Greeting>
      <Err msg={error} />
      {busy > 0 && <div className="notice row" role="status"><span className="spinner" aria-hidden="true" />{t("Reading {n} invoices…", { n: busy })}</div>}
      <div className="col dash">
        <div className="grid g4 tiles">
          <Tile label={t("Invoices received")} value={num(c.received)} delta={<Delta now={c.received} before={b.received} good="none" />}
            spark={daily((d) => d.auto + d.person + d.review + d.rejected)} />
          <Tile label={t("Approved value")} value={sar(c.value.approved)} title={money(c.value.approved, "SAR")} delta={<Delta now={c.value.approved} before={b.value.approved} good="none" />}
            spark={daily((d) => d.auto + d.person)} foot={otherFoot} />
          <Tile label={t("Rejected value")} value={sar(c.value.rejected)} title={money(c.value.rejected, "SAR")} delta={<Delta now={c.value.rejected} before={b.value.rejected} good="none" />}
            spark={daily((d) => d.rejected)} />
          <Tile label={t("Average time to decide")} value={dur(c.avg_time_to_review_s)}
            delta={<Delta now={c.avg_time_to_review_s} before={b.avg_time_to_review_s} good="down" />} spark={[]}
            foot={t("for invoices a person decided")} />
        </div>

        <section className="panel hero">
          <div className="hero-top">
            <div className="headline"><b className="num">{pct(c.auto_approve_rate)}</b><span>{t("cleared without a person")}</span>
              <Delta now={c.auto_approve_rate} before={b.auto_approve_rate} good="up" points /></div>
            <div className="kpis">
              <div className="kpi"><b className="num">{num(s.review_queue)}</b><span>{t("waiting in the review queue")}</span></div>
              <div className="kpi"><b className="num">{num(s.human_corrected)}</b><span>{t("fixed by a reviewer")}</span></div>
            </div>
          </div>
          {sum > 0 && <div className="strip" role="img" aria-label={parts.map((x) => `${t(x.label)}: ${num(x.n)}`).join("، ")}>
            {parts.filter((x) => x.n).map((x) => <div key={x.k} className={x.k} style={{ flexGrow: x.n }}>{x.n / sum > 0.07 ? num(x.n) : ""}</div>)}
          </div>}
          <OutcomeChart series={p.series} />
        </section>

        {p.insight && (
          <section className="panel insight">
            <span className="insight-tag">{t("Worth a look")}</span>
            <p>{t("“{rule}” failed {n} times in this period, against {m} in the period before.", { rule: t(p.insight.rule), n: p.insight.current, m: p.insight.previous })}</p>
            <p className="muted small">{t("Check whether the rule or the vendors behind it changed. A dry run on the Rules page shows what an edit would do before you save it.")}</p>
            <div><button className="btn small" onClick={() => go("rules")}>{t("Open the rules")}</button></div>
          </section>
        )}

        <div className="grid g2">
          <Waiting p={p} />
          <Feed rows={activity} />
        </div>

        <div className="grid g2">
          <div className="panel">
            <h2>{t("Rules that fail most")}</h2>
            {p.top_failing.length === 0 ? <p className="muted">{t("Nothing has failed a rule in this period.")}</p> :
              p.top_failing.map((f) => <div className="hbar" key={f.rule}><span title={t(f.rule)}>{t(f.rule)}</span><span className="t"><i style={{ width: `${(f.count / maxFail) * 100}%` }} /></span><b className="num">{num(f.count)}</b></div>)}
          </div>
          <div className="panel">
            <h2>{t("Top rejection reasons")}</h2>
            {p.top_rejections.length === 0 ? <p className="muted">{t("Nothing has been rejected in this period.")}</p> :
              p.top_rejections.map((f) => <div className="hbar bad" key={f.reason}><span title={t(f.reason)}>{t(f.reason)}</span><span className="t"><i style={{ width: `${(f.count / maxReason) * 100}%` }} /></span><b className="num">{num(f.count)}</b></div>)}
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
        <p className="muted small dash-note">{t("Amounts are totals in SAR, as read from the invoices. Invoices in other currencies are counted, not converted.")}</p>
      </div>
    </>
  );
}
