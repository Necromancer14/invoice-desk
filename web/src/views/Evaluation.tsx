import { useState } from "react";
import { api, session } from "../api";
import type { EvalResult } from "../types";
import { Err, Head, STATUS_LABEL, can, num, pct, tk, useApp, useLoad, when } from "../common";
import type { Status } from "../types";

interface EvalAll { rules: EvalResult | null; ai: (EvalResult & { provider?: string }) | null; recorded_ai: EvalResult | null }

const FORMAT: Record<string, string> = { txt: tk("Text"), pdf: tk("PDF with text"), png: tk("Image (needs vision)") };
const LANG: Record<string, string> = { en: tk("English"), ar: tk("Arabic"), bi: tk("Bilingual"), hard: tk("Unusual wording") };
const SCENARIO: Record<string, string> = {
  clean: tk("Clean invoice"), prompt_injection: tk("Hidden instruction inside the invoice"), bad_vat: tk("Malformed seller VAT number"),
  vat_rate: tk("Wrong VAT rate"), totals: tk("Totals do not add up"), future_date: tk("Issue date in the future"),
  duplicate: tk("Duplicate of an earlier invoice"), qr_mismatch: tk("QR code disagrees with printed total"), non_sar: tk("Foreign currency"),
  over_limit: tk("High value invoice"), missing_vat: tk("Seller VAT number missing"), due_before_issue: tk("Due date before issue date"),
};

function Metrics({ r, title, note }: { r: EvalResult; title: string; note?: string }) {
  const { t } = useApp();
  const [show, setShow] = useState(false);
  const wrong = r.rows.filter((x) => !x.agree);
  const version = (r as unknown as { rules_version?: number }).rules_version;
  const decision = (s: string) => (s in STATUS_LABEL ? t(STATUS_LABEL[s as Status]) : s.replace(/_/g, " "));
  return (
    <div className="panel">
      <h2>{title}</h2>
      <p className="muted small">
        {t("{n} invoices", { n: r.count })} · {t("rules version {v}", { v: version ?? "–" })}{r.ran_at ? ` · ${when(r.ran_at)}` : ""}{note ? ` · ${note}` : ""}
      </p>
      <div className="facts" style={{ marginTop: 12 }}>
        <div className="fact"><b>{pct(r.decision_agreement)}</b><span>{t("same decision as the answer key")}</span></div>
        <div className="fact"><b>{pct(r.field_accuracy)}</b><span>{t("fields read correctly")}</span></div>
        <div className="fact"><b>{pct(r.auto_approve_rate)}</b><span>{t("approved without a person")}</span></div>
        <div className="fact"><b style={{ color: r.unsafe_auto_approvals ? "var(--red)" : undefined }}>{num(r.unsafe_auto_approvals)}</b><span>{t("approved when it should not have been")}</span></div>
        <div className="fact"><b>{num(r.false_rejections)}</b><span>{t("wrongly rejected")}</span></div>
      </div>
      <h3 style={{ margin: "20px 0 6px" }}>{t("By kind of invoice")}</h3>
      <div className="tw"><table><thead><tr><th>{t("Kind")}</th><th className="n">{t("Invoices")}</th><th className="n">{t("Right decision")}</th><th className="n">{t("Fields correct")}</th></tr></thead><tbody>
        {Object.entries(r.by_format).map(([k, b]) => <tr key={k}><td>{FORMAT[k] ? t(FORMAT[k]) : k}</td><td className="n">{num(b.n)}</td><td className="n">{pct(b.agree / b.n)}</td><td className="n">{pct(b.fields_ok / b.fields_total)}</td></tr>)}
        {Object.entries(r.by_lang).map(([k, b]) => <tr key={k}><td>{LANG[k] ? t(LANG[k]) : k}</td><td className="n">{num(b.n)}</td><td className="n">{pct(b.agree / b.n)}</td><td className="n">{pct(b.fields_ok / b.fields_total)}</td></tr>)}
      </tbody></table></div>
      <p style={{ marginTop: 14 }}><button className="btn small" onClick={() => setShow(!show)}>{show ? t("Hide the {n} disagreements", { n: wrong.length }) : t("Show the {n} disagreements", { n: wrong.length })}</button></p>
      {show && <div className="tw"><table><thead><tr><th>{t("File")}</th><th>{t("Scenario")}</th><th>{t("Expected")}</th><th>{t("Got")}</th></tr></thead><tbody>
        {wrong.map((x) => <tr key={x.id}><td><bdi dir="ltr">{x.file}</bdi></td><td>{SCENARIO[x.scenario] ? t(SCENARIO[x.scenario]) : x.scenario.replace(/_/g, " ")}</td><td>{decision(x.expected)}</td><td>{decision(x.got)}</td></tr>)}</tbody></table></div>}
    </div>
  );
}

export default function Evaluation() {
  const { t, role, toast } = useApp();
  const { data, error, reload } = useLoad(() => api<EvalAll>("/evaluation"), []);
  const [running, setRunning] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const hasKey = session.aiReady();

  async function run(mode: "rules" | "ai") {
    setRunning(mode); setErr(null);
    try {
      const { job } = await api<{ job: string }>("/evaluation/run", { body: { mode }, ai: mode === "ai" });
      for (let i = 0; i < 600; i++) {
        await new Promise((r) => setTimeout(r, 1500));
        const j = await api<{ status: string; error?: string }>(`/evaluation/jobs/${job}`);
        if (j.status === "done") { toast(t("Evaluation finished")); reload(); break; }
        if (j.status === "error") throw new Error(j.error);
      }
    } catch (e) { setErr((e as Error).message); } finally { setRunning(null); }
  }
  return (
    <>
      <Head title={t("Evaluation")} sub={t("How well does the system do on 60 made-up invoices where the right answer is known? Run it again after changing rules to see the effect.")}>
        {can(role, "admin") && (
          <div className="row wrap">
            <button className="btn primary" disabled={!!running} onClick={() => run("rules")}>{running === "rules" ? t("Running…") : t("Run with built-in rules")}</button>
            <button className="btn" disabled={!!running || !hasKey} title={hasKey ? "" : t("Pick a provider and add its key in Settings")} onClick={() => run("ai")}>{running === "ai" ? t("Running (a few minutes)…") : t("Run with my AI model")}</button>
          </div>
        )}
      </Head>
      <Err msg={error || err} />
      <div className="notice" style={{ marginBottom: 14 }}>{t("The invoices are synthetic and follow formats the rule-based reader was written against, so its scores are optimistic. Treat them as a way to compare changes, not as a claim about real-world accuracy. Running with an AI model sends the 60 made-up invoices to the provider you chose, using your key. Free plans have rate limits, so the run can take a few minutes or fail partway; failed invoices fall back to the built-in reader and are marked in their trace.")}</div>
      <div className="col" style={{ gap: 16 }}>
        {data?.rules && <Metrics r={data.rules} title={t("Built-in rules")} />}
        {data?.ai && <Metrics r={data.ai} title={data.ai.provider ? t("AI model ({provider}), your run", { provider: data.ai.provider }) : t("AI model, your run")} />}
        {!data?.ai && data?.recorded_ai && <Metrics r={data.recorded_ai} title={t("AI model, recorded run shipped with the project")} note={t("not live")} />}
        {data && !data.rules && !data.ai && !data.recorded_ai && <div className="panel muted">{t("No results yet. Run the evaluation to fill this page.")}</div>}
      </div>
    </>
  );
}
