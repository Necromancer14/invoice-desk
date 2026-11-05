import { useEffect, useState } from "react";
import { api, session } from "../api";
import type { AiLastRun, AiTotals, EvalResult, Provider, Status } from "../types";
import { Err, Head, STATUS_LABEL, can, day, num, pct, tk, useApp, useLoad, when } from "../common";

interface EvalAll { rules: EvalResult | null; ai_models: AiTotals[]; ai_last: AiLastRun | null; recorded_ai: EvalResult | null }
interface Job { status: string; error?: string; done?: number; total?: number; errors?: number; message?: string; stopped?: AiLastRun["stopped"] }
interface AiOptions { sample_size: number; rpm: number; only_new: boolean; seed: number }

const FORMAT: Record<string, string> = { txt: tk("Text"), pdf: tk("PDF with text"), png: tk("Image (needs vision)") };
const LANG: Record<string, string> = { en: tk("English"), ar: tk("Arabic"), bi: tk("Bilingual"), hard: tk("Unusual wording") };
const SCENARIO: Record<string, string> = {
  clean: tk("Clean invoice"), prompt_injection: tk("Hidden instruction inside the invoice"), bad_vat: tk("Malformed seller VAT number"),
  vat_rate: tk("Wrong VAT rate"), totals: tk("Totals do not add up"), future_date: tk("Issue date in the future"),
  duplicate: tk("Duplicate of an earlier invoice"), qr_mismatch: tk("QR code disagrees with printed total"), non_sar: tk("Foreign currency"),
  over_limit: tk("High value invoice"), missing_vat: tk("Seller VAT number missing"), due_before_issue: tk("Due date before issue date"),
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
      <div className="facts" style={{ marginTop: 12 }}>
        <div className="fact"><b>{pct(r.decision_agreement)}</b><span>{t("same decision as the answer key")}</span><small className="n-note">{nInv(n)}</small></div>
        <div className="fact"><b>{pct(r.field_accuracy)}</b><span>{t("fields read correctly")}</span><small className="n-note">{t("n = {n} fields", { n: r.fields_total ?? 0 })}</small></div>
        <div className="fact"><b>{pct(r.auto_approve_rate)}</b><span>{t("approved without a person")}</span><small className="n-note">{nInv(n)}</small></div>
        <div className="fact"><b style={{ color: r.unsafe_auto_approvals ? "var(--red)" : undefined }}>{num(r.unsafe_auto_approvals)}</b><span>{t("approved when it should not have been")}</span><small className="n-note">{nInv(n)}</small></div>
        <div className="fact"><b>{num(r.false_rejections)}</b><span>{t("wrongly rejected")}</span><small className="n-note">{nInv(n)}</small></div>
      </div>
      <h3 style={{ margin: "20px 0 6px" }}>{t("By kind of invoice")}</h3>
      <div className="tw"><table><thead><tr><th>{t("Kind")}</th><th className="n">{t("Invoices (n)")}</th><th className="n">{t("Right decision")}</th><th className="n">{t("Fields correct")}</th></tr></thead><tbody>
        {Object.entries(r.by_format).map(([k, b]) => <tr key={k}><td>{FORMAT[k] ? t(FORMAT[k]) : k}</td><td className="n">{num(b.n)}</td><td className="n">{pct(b.agree / b.n)}</td><td className="n">{pct(b.fields_ok / b.fields_total)}</td></tr>)}
        {Object.entries(r.by_lang).map(([k, b]) => <tr key={k}><td>{LANG[k] ? t(LANG[k]) : k}</td><td className="n">{num(b.n)}</td><td className="n">{pct(b.agree / b.n)}</td><td className="n">{pct(b.fields_ok / b.fields_total)}</td></tr>)}
      </tbody></table></div>
      {wrong.length > 0 && <p style={{ marginTop: 14 }}><button className="btn small" onClick={() => setShow(!show)}>{show ? t("Hide the {n} disagreements", { n: wrong.length }) : t("Show the {n} disagreements", { n: wrong.length })}</button></p>}
      {show && <div className="tw"><table><thead><tr><th>{t("File")}</th><th>{t("Scenario")}</th><th>{t("Expected")}</th><th>{t("Got")}</th></tr></thead><tbody>
        {wrong.map((x) => <tr key={x.id}><td><bdi dir="ltr">{x.file}</bdi></td><td>{SCENARIO[x.scenario] ? t(SCENARIO[x.scenario]) : x.scenario.replace(/_/g, " ")}</td><td>{decision(x.expected)}</td><td>{decision(x.got)}</td></tr>)}</tbody></table></div>}
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
    <div className={`notice ${kind} col`} style={{ gap: 6 }}>
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
        {show && <ul className="small" style={{ margin: 0, paddingInlineStart: 18 }}>{last.error_rows.map((e) => <li key={e.id}><bdi dir="ltr">{e.file}</bdi>: <span dir="auto">{e.error}</span></li>)}</ul>}
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

  async function run(mode: "rules" | "ai", opts?: AiOptions) {
    setRunning(mode); setErr(null); setJob(null);
    try {
      const { job: id } = await api<{ job: string }>("/evaluation/run", { body: { mode, ...opts }, ai: mode === "ai" });
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
      <div className="notice" style={{ marginBottom: 14 }}>{t("The invoices are synthetic and follow formats the rule-based reader was written against, so its scores are optimistic. Treat them as a way to compare changes, not as a claim about real-world accuracy. Running with an AI model sends the chosen invoices to the provider you picked, using your key.")}</div>
      <div className="col" style={{ gap: 16 }}>
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
        {data && !data.rules && !data.ai_models.length && !data.recorded_ai && <div className="panel muted">{t("No results yet. Run the evaluation to fill this page.")}</div>}
      </div>
    </>
  );
}
