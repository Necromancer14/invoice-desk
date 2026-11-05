import { useState } from "react";
import { api, session } from "../api";
import type { EvalResult } from "../types";
import { Err, Head, can, pct, useApp, useLoad, when } from "../common";

interface EvalAll { rules: EvalResult | null; ai: (EvalResult & { provider?: string }) | null; recorded_ai: EvalResult | null }

function Metrics({ r, title, note }: { r: EvalResult; title: string; note?: string }) {
  const [show, setShow] = useState(false);
  const wrong = r.rows.filter((x) => !x.agree);
  return (
    <div className="panel">
      <h2>{title}</h2>
      <p className="muted small">{r.count} invoices · rules version {(r as unknown as { rules_version?: number }).rules_version ?? "–"}{r.ran_at ? ` · ${when(r.ran_at)}` : ""}{note ? ` · ${note}` : ""}</p>
      <div className="facts" style={{ marginTop: 12 }}>
        <div className="fact"><b>{pct(r.decision_agreement)}</b><span>same decision as the answer key</span></div>
        <div className="fact"><b>{pct(r.field_accuracy)}</b><span>fields read correctly</span></div>
        <div className="fact"><b>{pct(r.auto_approve_rate)}</b><span>approved without a person</span></div>
        <div className="fact"><b style={{ color: r.unsafe_auto_approvals ? "var(--red)" : undefined }}>{r.unsafe_auto_approvals}</b><span>approved when it should not have been</span></div>
        <div className="fact"><b>{r.false_rejections}</b><span>wrongly rejected</span></div>
      </div>
      <h3 style={{ margin: "20px 0 6px" }}>By kind of invoice</h3>
      <div className="tw"><table><thead><tr><th>Kind</th><th className="n">Invoices</th><th className="n">Right decision</th><th className="n">Fields correct</th></tr></thead><tbody>
        {Object.entries(r.by_format).map(([k, b]) => <tr key={k}><td>{({ txt: "Text", pdf: "PDF with text", png: "Image (needs vision)" } as Record<string, string>)[k] ?? k}</td><td className="n">{b.n}</td><td className="n">{pct(b.agree / b.n)}</td><td className="n">{pct(b.fields_ok / b.fields_total)}</td></tr>)}
        {Object.entries(r.by_lang).map(([k, b]) => <tr key={k}><td>{({ en: "English", ar: "Arabic", bi: "Bilingual", hard: "Unusual wording" } as Record<string, string>)[k] ?? k}</td><td className="n">{b.n}</td><td className="n">{pct(b.agree / b.n)}</td><td className="n">{pct(b.fields_ok / b.fields_total)}</td></tr>)}
      </tbody></table></div>
      <p style={{ marginTop: 14 }}><button className="btn small" onClick={() => setShow(!show)}>{show ? "Hide" : "Show"} the {wrong.length} disagreements</button></p>
      {show && <div className="tw"><table><thead><tr><th>File</th><th>Scenario</th><th>Expected</th><th>Got</th></tr></thead><tbody>
        {wrong.map((x) => <tr key={x.id}><td>{x.file}</td><td>{x.scenario.replace(/_/g, " ")}</td><td>{x.expected.replace("_", " ")}</td><td>{x.got.replace("_", " ")}</td></tr>)}</tbody></table></div>}
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
        if (j.status === "done") { toast("Evaluation finished"); reload(); break; }
        if (j.status === "error") throw new Error(j.error);
      }
    } catch (e) { setErr((e as Error).message); } finally { setRunning(null); }
  }
  return (
    <>
      <Head title={t("Evaluation")} sub="How well does the system do on 60 made-up invoices where the right answer is known? Run it again after changing rules to see the effect.">
        {can(role, "admin") && (
          <div className="row wrap">
            <button className="btn primary" disabled={!!running} onClick={() => run("rules")}>{running === "rules" ? "Running…" : "Run with built-in rules"}</button>
            <button className="btn" disabled={!!running || !hasKey} title={hasKey ? "" : "Pick a provider and add its key in Settings"} onClick={() => run("ai")}>{running === "ai" ? "Running (a few minutes)…" : "Run with my AI model"}</button>
          </div>
        )}
      </Head>
      <Err msg={error || err} />
      <div className="notice" style={{ marginBottom: 14 }}>The invoices are synthetic and follow formats the rule-based reader was written against, so its scores are optimistic. Treat them as a way to compare changes, not as a claim about real-world accuracy. Running with an AI model sends the 60 made-up invoices to the provider you chose, using your key. Free plans have rate limits, so the run can take a few minutes or fail partway; failed invoices fall back to the built-in reader and are marked in their trace.</div>
      <div className="col" style={{ gap: 16 }}>
        {data?.rules && <Metrics r={data.rules} title="Built-in rules" />}
        {data?.ai && <Metrics r={data.ai} title={`AI model${data.ai.provider ? ` (${data.ai.provider})` : ""}, your run`} />}
        {!data?.ai && data?.recorded_ai && <Metrics r={data.recorded_ai} title="AI model, recorded run shipped with the project" note="not live" />}
        {data && !data.rules && !data.ai && !data.recorded_ai && <div className="panel muted">No results yet. Run the evaluation to fill this page.</div>}
      </div>
    </>
  );
}
