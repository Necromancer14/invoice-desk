import { useEffect, useState } from "react";
import { api, session } from "../api";
import type { AiLastRun, AiTotals, CopilotEval, CopilotRow, EvalResult, Provider, Recommendation, Status } from "../types";
import { Err, Head, STATUS_LABEL, can, day, num, pct, tk, useApp, useLoad, when } from "../common";
import { ItemRow, REC_SHORT } from "./Copilot";

interface EvalAll { rules: EvalResult | null; ai_models: AiTotals[]; ai_last: AiLastRun | null; recorded_ai: EvalResult | null; copilot_ai: CopilotEval | null }
interface Job { status: string; error?: string; done?: number; total?: number; errors?: number; message?: string; stopped?: AiLastRun["stopped"] }
interface AiOptions { sample_size: number; rpm: number; only_new: boolean; seed: number }

const FORMAT: Record<string, string> = { txt: tk("Text"), pdf: tk("PDF with text"), png: tk("Image (needs vision)"), xml: tk("UBL XML") };
const LANG: Record<string, string> = { en: tk("English"), ar: tk("Arabic"), bi: tk("Bilingual"), hard: tk("Unusual wording") };
const SCENARIO: Record<string, string> = {
  clean: tk("Clean invoice"), prompt_injection: tk("Hidden instruction inside the invoice"), bad_vat: tk("Malformed seller VAT number"),
  vat_rate: tk("Wrong VAT rate"), totals: tk("Totals do not add up"), future_date: tk("Issue date in the future"),
  duplicate: tk("Duplicate of an earlier invoice"), qr_mismatch: tk("QR code disagrees with printed total"), non_sar: tk("Foreign currency"),
  over_limit: tk("High value invoice"), missing_vat: tk("Seller VAT number missing"), due_before_issue: tk("Due date before issue date"),
  vat_digits_spaced: tk("VAT number in Arabic digits, grouped with spaces"), arabic_decimals: tk("Arabic-Indic digits and decimal separators"), zero_rated: tk("Zero-rated line, VAT on the rest only"), exempt: tk("Exempt line, VAT on the rest only"), zero_rated_wrong: tk("VAT charged on a zero-rated line"), hijri_date: tk("Hijri issue date"), hijri_future: tk("Hijri issue date in the future"), qr_missing: tk("No QR code on the invoice"), simplified: tk("Simplified tax invoice"),
  vendor_ok: tk("Known vendor, IBAN and PO agree"), vendor_fuzzy: tk("Vendor name written differently"), iban_changed: tk("IBAN differs from the vendor master"),
  blocked_vendor: tk("Blocked vendor"), unknown_vendor: tk("Vendor not in the vendor master"), vendor_vat_mismatch: tk("VAT number differs from the vendor master"),
  po_over: tk("Invoice above its purchase order"),
};
const DEFAULTS: AiOptions = { sample_size: 20, rpm: 4, only_new: false, seed: 1 };
const OPTIONS_KEY = "id-eval-ai";

/** Last-used AI evaluation options, remembered in this browser only. */
function loadOptions(): AiOptions {
  try { return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(OPTIONS_KEY) || "{}") }; } catch { return DEFAULTS; }
}

/** hideCount: the note already says how many invoices were evaluated. */
function Metrics({ r, title, note, hideCount }: { r: EvalResult; title: string; note?: string; hideCount?: boolean }) {
  const { t } = useApp();
  const [show, setShow] = useState(false);
  const wrong = r.rows.filter((x) => !x.agree);
  const n = r.count;
  const nInv = (count: number) => t("n = {n}", { n: count });
  const decision = (s: string) => (s in STATUS_LABEL ? t(STATUS_LABEL[s as Status]) : s.replace(/_/g, " "));
  return (
    <div className="panel">
      <h2>{title}</h2>
      <p className="muted small">
        {[hideCount ? "" : t("{n} invoices", { n }), r.rules_version != null ? t("rules version {v}", { v: r.rules_version }) : "", r.ran_at ? when(r.ran_at) : "", note ?? ""].filter(Boolean).join(" · ")}
      </p>
      <div className="facts mt3">
        <div className="fact"><b>{pct(r.decision_agreement)}</b><span>{t("same decision as the answer key")}</span><small className="n-note">{nInv(n)}</small></div>
        <div className="fact"><b>{pct(r.field_accuracy)}</b><span>{t("fields read correctly")}</span><small className="n-note">{t("n = {n} fields", { n: r.fields_total ?? 0 })}</small></div>
        <div className="fact"><b>{pct(r.auto_approve_rate)}</b><span>{t("approved without a person")}</span><small className="n-note">{nInv(n)}</small></div>
        <div className="fact"><b className={r.unsafe_auto_approvals ? "bad-figure" : undefined}>{num(r.unsafe_auto_approvals)}</b><span>{t("approved when it should not have been")}</span><small className="n-note">{nInv(n)}</small></div>
        <div className="fact"><b>{num(r.false_rejections)}</b><span>{t("wrongly rejected")}</span><small className="n-note">{nInv(n)}</small></div>
      </div>
      <h3 className="sec-title mt5">{t("By kind of invoice")}</h3>
      <div className="tw"><table><thead><tr><th>{t("Kind")}</th><th className="n">{t("Invoices (n)")}</th><th className="n">{t("Right decision")}</th><th className="n">{t("Fields correct")}</th></tr></thead><tbody>
        {Object.entries(r.by_format).map(([k, b]) => <tr key={k}><td>{FORMAT[k] ? t(FORMAT[k]) : k}</td><td className="n">{num(b.n)}</td><td className="n">{pct(b.agree / b.n)}</td><td className="n">{pct(b.fields_ok / b.fields_total)}</td></tr>)}
        {Object.entries(r.by_lang).map(([k, b]) => <tr key={k}><td>{LANG[k] ? t(LANG[k]) : k}</td><td className="n">{num(b.n)}</td><td className="n">{pct(b.agree / b.n)}</td><td className="n">{pct(b.fields_ok / b.fields_total)}</td></tr>)}
      </tbody></table></div>
      {wrong.length > 0 && <p className="mt3"><button className="btn small" onClick={() => setShow(!show)}>{show ? t("Hide the {n} disagreements", { n: wrong.length }) : t("Show the {n} disagreements", { n: wrong.length })}</button></p>}
      {show && <div className="tw"><table><thead><tr><th>{t("File")}</th><th>{t("Scenario")}</th><th>{t("Expected")}</th><th>{t("Got")}</th></tr></thead><tbody>
        {wrong.map((x) => <tr key={x.id}><td><bdi dir="ltr">{x.file}</bdi></td><td>{SCENARIO[x.scenario] ? t(SCENARIO[x.scenario]) : x.scenario.replace(/_/g, " ")}</td><td>{decision(x.expected)}</td><td>{decision(x.got)}</td></tr>)}</tbody></table></div>}
    </div>
  );
}

const scenarioLabel = (t: (s: string) => string, s: string) => (SCENARIO[s] ? t(SCENARIO[s]) : s.replace(/_/g, " "));

/** How often the review copilot's suggestion matched the right decision, on the items the desk sent to review. */
function CopilotMetrics({ c, title }: { c: CopilotEval; title: string }) {
  const { t, lang } = useApp();
  const [show, setShow] = useState<"" | "wrong" | "deferred">("");
  const ok = c.rows.filter((x) => x.outcome === "ok");
  const wrong = ok.filter((x) => !x.agree && !x.deferred);
  const deferred = ok.filter((x) => x.deferred);
  const agreed = ok.filter((x) => x.agree && !x.deferred).length;       // the figure's numerator; c.answered is its n
  const errors = c.rows.filter((x) => x.outcome === "error");
  const nInv = t("n = {n}", { n: c.count });
  const said = (x: CopilotRow) => {
    const s = x.summary ? (lang === "ar" ? x.summary.ar || x.summary.en : x.summary.en || x.summary.ar) : "";
    const items = x.reasons ?? [];
    return !s && !items.length ? "–" : <>
      {s && <div dir="auto">{s}</div>}
      {items.length > 0 && <ul className="cp-findings">{items.map((it, i) => <ItemRow key={i} it={it} />)}</ul>}</>;
  };
  const list = (rows: CopilotRow[], key: "wrong" | "deferred", label: string) => rows.length > 0 && (
    <p className="mt3"><button className="btn small" onClick={() => setShow(show === key ? "" : key)}>{label}</button></p>);
  const rec = (r?: Recommendation) => (r ? t(REC_SHORT[r]) : "–");
  const meta = [
    c.mode === "gemini" && c.model ? `${c.model}` : "",
    c.mode === "gemini" ? t("{done} of {n} review items, picked by seed {seed}", { done: c.count, n: c.review_items ?? 0, seed: c.seed ?? 1 }) : t("{n} invoices", { n: c.count }),
    c.errors ? t("{n} errors", { n: c.errors }) : "", c.rules_version != null ? t("rules version {v}", { v: c.rules_version }) : "", c.ran_at ? when(c.ran_at) : "",
  ].filter(Boolean);
  return (
    <div className="panel">
      <h2>{title}</h2>
      <p className="muted small"><bdi>{meta.join(" · ")}</bdi></p>
      <p className="small mt2">{t("Measured on synthetic samples only: the invoices the built-in reader sends to review. The right decision comes from the answer key; where the key expects review, it is our judgement for each kind of problem, written down in evaluation.py. When the file could not be read or was read with low confidence, a suggestion to find out more is counted as deferred, not as wrong, and is left out of the agreement figure. A suggestion to find out more is never unsafe.")}
        {c.mode === "gemini" && " " + t("For Gemini, an item is deferred only if the file was still unreadable after its own re-read; if it read the file and still suggested finding out more, that counts as an answer.")}</p>
      <div className="facts mt3">
        <div className="fact"><b>{pct(c.agreement)}</b><span>{t("agreement with the right decision, on the items it could read")}</span><small className="n-note">{t("{a} of {n} agree · not counted: {d} deferred", { a: agreed, n: c.answered, d: c.deferred })}</small></div>
        <div className="fact"><b>{pct(c.deferral_rate)}</b><span>{t("deferred: it asked to find out more because the file could not be read")}</span><small className="n-note">{t("{d} of {n} items", { d: c.deferred, n: c.count })}</small></div>
        <div className="fact"><b className={c.unsafe_approves ? "bad-figure" : undefined}>{num(c.unsafe_approves)}</b><span>{t("suggested approving when it should not have")}</span><small className="n-note">{nInv}</small></div>
      </div>
      <p className="muted small mt2">{[t("{n} steps per invoice", { n: num(c.avg_steps, 1) }), c.mode === "gemini" ? t("{a} tokens in, {b} out", { a: num(c.avg_tokens_in), b: num(c.avg_tokens_out) }) : ""].filter(Boolean).join(" · ")}</p>
      <h3 className="sec-title mt5">{t("By kind of invoice")}</h3>
      <div className="tw"><table><thead><tr><th>{t("Kind")}</th><th className="n">{t("Invoices (n)")}</th><th className="n">{t("Deferred")}</th><th className="n">{t("Right suggestion")}</th><th className="n">{t("Unsafe approve")}</th></tr></thead><tbody>
        {Object.entries(c.by_scenario).map(([k, b]) => <tr key={k}><td>{scenarioLabel(t, k)}</td><td className="n">{num(b.n)}</td><td className="n">{num(b.deferred)}</td>
          <td className="n">{b.n > b.deferred ? t("{n} of {total}", { n: b.agree, total: b.n - b.deferred }) : "–"}</td><td className="n">{num(b.unsafe)}</td></tr>)}
        {/* the same numbers as the headline: agreed of answered, so the table and the figure cannot disagree */}
        <tr className="total-row"><th scope="row">{t("All items")}</th><td className="n">{num(c.count)}</td><td className="n">{num(c.deferred)}</td>
          <td className="n">{c.answered > 0 ? `${t("{n} of {total}", { n: agreed, total: c.answered })} (${pct(c.agreement)})` : "–"}</td><td className="n">{num(c.unsafe_approves)}</td></tr>
      </tbody></table></div>
      {list(wrong, "wrong", show === "wrong" ? t("Hide the {n} disagreements", { n: wrong.length }) : t("Show the {n} disagreements", { n: wrong.length }))}
      {list(deferred, "deferred", show === "deferred" ? t("Hide the {n} deferred items", { n: deferred.length }) : t("Show the {n} deferred items", { n: deferred.length }))}
      {(show === "wrong" || show === "deferred") && <div className="tw"><table><thead><tr><th>{t("File")}</th><th>{t("Scenario")}</th><th>{t("Right decision")}</th><th>{t("Suggested")}</th><th>{t("What it said")}</th></tr></thead><tbody>
        {(show === "wrong" ? wrong : deferred).map((x) => <tr key={x.id}><td><bdi dir="ltr">{x.file}</bdi></td><td>{scenarioLabel(t, x.scenario)}</td><td>{rec(x.correct)}</td><td>{rec(x.recommended)}</td><td>{said(x)}</td></tr>)}</tbody></table></div>}
      {errors.length > 0 && <ul className="small plain-list mt3">{errors.map((e) => <li key={e.id}><bdi dir="ltr">{e.file}</bdi>: <span dir="auto">{e.error}</span></li>)}</ul>}
    </div>
  );
}

interface CopilotOptions { sample_size: number; rpm: number; seed: number }
const COPILOT_DEFAULTS: CopilotOptions = { sample_size: 10, rpm: 4, seed: 1 };

function CopilotRunForm({ running, onRun }: { running: boolean; onRun: (o: CopilotOptions) => void }) {
  const { t } = useApp();
  const [o, setO] = useState<CopilotOptions>(COPILOT_DEFAULTS);
  const ready = session.provider === "gemini" && session.aiReady();
  const setNum = (k: keyof CopilotOptions, lo: number, hi: number) => (e: React.ChangeEvent<HTMLInputElement>) => {
    const v = Math.round(Number(e.target.value));
    setO({ ...o, [k]: Number.isFinite(v) ? Math.min(hi, Math.max(lo, v)) : lo });
  };
  return (
    <div className="panel col">
      <h2>{t("Evaluate the copilot with Gemini")}</h2>
      <p className="muted small">{t("The built-in reader reads every sample for free, then Gemini investigates a sample of the invoices that land in review, paced for free-tier limits. Each investigation takes several calls. A failed investigation is counted as an error, never handed to the rule-based copilot.")}</p>
      {!ready && <div className="notice warn">{t("Pick Google Gemini and add its key in Settings")}</div>}
      <div className="grid eval-opts">
        <label className="f">{t("How many invoices")}<input type="number" dir="ltr" min={1} max={41} value={o.sample_size} onChange={setNum("sample_size", 1, 41)} /></label>
        <label className="f">{t("Requests per minute")}<input type="number" dir="ltr" min={1} max={60} value={o.rpm} onChange={setNum("rpm", 1, 60)} /></label>
        <label className="f">{t("Sample seed")} <span className="hint">{t("(same seed, same invoices)")}</span><input type="number" dir="ltr" min={0} value={o.seed} onChange={setNum("seed", 0, 1_000_000)} /></label>
      </div>
      <div className="row wrap">
        <button className="btn primary" disabled={running || !ready} onClick={() => onRun(o)}>{running ? t("Running…") : t("Run the copilot with Gemini")}</button>
      </div>
    </div>
  );
}

/** "14 of 20 evaluated, 6 errors", and why a run stopped early. */
function RunOutcome({ last }: { last: AiLastRun }) {
  const { t } = useApp();
  const [show, setShow] = useState(false);
  const kind = last.stopped ? "warn" : last.errors ? "warn" : "ok";
  const notReached = last.picked - last.attempted;
  return (
    <div className={`notice ${kind} col gap-1`}>
      <b className="outcome">{[t("{done} of {n} evaluated", { done: last.evaluated, n: last.picked }), t("{n} errors", { n: last.errors }),
        ...(notReached ? [t("{n} not reached", { n: notReached })] : [])].reduce((a, b) => t("{a}, {b}", { a, b }))}</b>
      <span className="small">
        <bdi dir="ltr">{last.model}</bdi> · {when(last.ran_at)} · {t("sample seed {seed}", { seed: last.seed })} · {t("{n} requests a minute", { n: last.rpm })}
        {last.only_new ? ` · ${t("{n} already evaluated were skipped", { n: last.skipped })}` : ""}
      </span>
      {last.stopped && <span>{last.stopped.reason === "quota" ? t("Stopped: the daily quota for this model is used up. Run again tomorrow with “only invoices not yet evaluated” to continue.") : t("Stopped: the provider kept refusing requests after 3 retries. Try again later or lower the requests per minute.")}
        {" "}<span className="small" dir="auto">({last.stopped.message})</span></span>}
      {last.error_rows.length > 0 && <>
        <span><button className="btn small" onClick={() => setShow(!show)}>{show ? t("Hide errors") : t("Show errors")}</button></span>
        {show && <ul className="small plain-list">{last.error_rows.map((e) => <li key={e.id}><bdi dir="ltr">{e.file}</bdi>: <span dir="auto">{e.error}</span></li>)}</ul>}
      </>}
      <span className="small">{t("Errors are left out of every percentage below.")}</span>
    </div>
  );
}

function AiRunForm({ running, onRun }: { running: boolean; onRun: (o: AiOptions) => void }) {
  const { t } = useApp();
  const [o, setO] = useState<AiOptions>(loadOptions);
  const { data: providers } = useLoad(() => api<Provider[]>("/llm/providers"), []);
  useEffect(() => { try { localStorage.setItem(OPTIONS_KEY, JSON.stringify(o)); } catch { /* storage blocked */ } }, [o]);
  const hasKey = session.aiReady();
  const p = providers?.find((x) => x.id === session.provider);
  const model = session.model || p?.model || "";
  const minutes = Math.max(1, Math.ceil(o.sample_size / o.rpm));
  const setNum = (k: keyof AiOptions, lo: number, hi: number) => (e: React.ChangeEvent<HTMLInputElement>) => {
    const v = Math.round(Number(e.target.value));
    setO({ ...o, [k]: Number.isFinite(v) ? Math.min(hi, Math.max(lo, v)) : lo });
  };
  return (
    <div className="panel col">
      <h2>{t("Evaluate an AI model")}</h2>
      <p className="muted small">{t("Free plans allow only a few requests a minute and a small number a day, so this takes a sample of the invoices that still covers every file type, language and kind of problem, and paces the calls. A call that fails is counted as an error, never handed to the built-in reader.")}</p>
      {!hasKey ? <div className="notice warn">{t("Pick a provider and add its key in Settings")}</div> : (
        <p className="small">{t("Model")}: <b><bdi dir="ltr">{p?.label ?? session.provider} · {model}</bdi></b></p>
      )}
      <div className="grid eval-opts">
        <label className="f">{t("How many invoices")}<input type="number" dir="ltr" min={1} max={60} value={o.sample_size} onChange={setNum("sample_size", 1, 60)} /></label>
        <label className="f">{t("Requests per minute")}<input type="number" dir="ltr" min={1} max={60} value={o.rpm} onChange={setNum("rpm", 1, 60)} /></label>
        <label className="f">{t("Sample seed")} <span className="hint">{t("(same seed, same invoices)")}</span><input type="number" dir="ltr" min={0} value={o.seed} onChange={setNum("seed", 0, 1_000_000)} /></label>
      </div>
      <label className="check"><input type="checkbox" checked={o.only_new} onChange={(e) => setO({ ...o, only_new: e.target.checked })} />{t("Only invoices not yet evaluated with this model")}</label>
      <div className="row wrap">
        <button className="btn primary" disabled={running || !hasKey} onClick={() => onRun(o)}>{running ? t("Running…") : t("Run with my AI model")}</button>
        <span className="muted small">{t("About {n} minutes at this pace.", { n: minutes })}</span>
      </div>
    </div>
  );
}

export default function Evaluation() {
  const { t, role, toast } = useApp();
  const { data, error, reload } = useLoad(() => api<EvalAll>("/evaluation"), []);
  const [running, setRunning] = useState<string | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const admin = can(role, "admin");

  async function run(mode: "rules" | "ai" | "copilot_ai", opts?: AiOptions | CopilotOptions) {
    setRunning(mode); setErr(null); setJob(null);
    try {
      const { job: id } = await api<{ job: string }>("/evaluation/run", { body: { mode, ...opts }, ai: mode !== "rules" });
      for (let i = 0; i < 4000; i++) {
        await new Promise((r) => setTimeout(r, 1500));
        const j = await api<Job>(`/evaluation/jobs/${id}`);
        setJob(j);
        if (j.status === "done") { toast(j.stopped ? t("Evaluation stopped early") : t("Evaluation finished")); reload(); break; }
        if (j.status === "error") throw new Error(j.error);
      }
    } catch (e) { setErr((e as Error).message); } finally { setRunning(null); }
  }
  return (
    <>
      <Head title={t("Evaluation")} sub={t("How well does the system do on 60 made-up invoices where the right answer is known? Run it again after changing rules to see the effect.")}>
        {admin && <button className="btn primary" disabled={!!running} onClick={() => run("rules")}>{running === "rules" ? t("Running…") : t("Run with built-in rules")}</button>}
      </Head>
      <Err msg={error || err} />
      <div className="notice mb">{t("The invoices are synthetic and follow formats the rule-based reader was written against, so its scores are optimistic. Treat them as a way to compare changes, not as a claim about real-world accuracy. Running with an AI model sends the chosen invoices to the provider you picked, using your key.")}</div>
      <div className="col gap-4">
        {data?.rules && <Metrics r={data.rules} title={t("Built-in rules")} />}
        {admin && <AiRunForm running={!!running} onRun={(o) => run("ai", o)} />}
        {running === "ai" && job && job.total != null && (
          <div className="notice" role="status">{t("{a}, {b}", { a: t("Evaluating {done} of {n}", { done: job.done ?? 0, n: job.total }), b: t("{n} errors so far", { n: job.errors ?? 0 }) })}</div>
        )}
        {data?.ai_last && <RunOutcome last={data.ai_last} />}
        {data?.ai_models.map((m) => (
          <Metrics key={`${m.provider}/${m.model}`} r={m} hideCount
            title={t("{model}, all runs combined", { model: `${m.model} (${m.provider})` })}
            note={[t("{done} of {n} invoices evaluated", { done: m.count, n: m.samples_total }), t("{n} errors", { n: m.errors ?? 0 }),
              m.first_at.slice(0, 10) === m.last_at.slice(0, 10) ? day(m.first_at) : `${day(m.first_at)} – ${day(m.last_at)}`].join(" · ")} />
        ))}
        {!data?.ai_models.length && data?.recorded_ai && <Metrics r={data.recorded_ai} title={t("AI model, recorded run shipped with the project")} note={t("not live")} />}
        {data?.rules?.copilot && <CopilotMetrics c={data.rules.copilot} title={t("Review copilot, rule-based")} />}
        {admin && <CopilotRunForm running={!!running} onRun={(o) => run("copilot_ai", o)} />}
        {running === "copilot_ai" && job && job.total != null && (
          <div className="notice" role="status">{t("{a}, {b}", { a: t("Evaluating {done} of {n}", { done: job.done ?? 0, n: job.total }), b: t("{n} errors so far", { n: job.errors ?? 0 }) })}</div>
        )}
        {data?.copilot_ai && <CopilotMetrics c={data.copilot_ai} title={t("Review copilot, Gemini")} />}
        {data && !data.rules && !data.ai_models.length && !data.recorded_ai && <div className="panel muted">{t("No results yet. Run the evaluation to fill this page.")}</div>}
      </div>
    </>
  );
}
