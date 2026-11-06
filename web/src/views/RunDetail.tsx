import { useEffect, useState } from "react";
import { api, fileBlobUrl } from "../api";
import type { Fields, RunDetail as Run } from "../types";
import { CheckMark, Err, FIELD_LABEL, StatusPill, can, money, num, pct, tk, useApp, when } from "../common";

/** ltr: codes, dates and amounts, typed and shown left-to-right even in Arabic. Labels come from FIELD_LABEL. */
const EDIT_FIELDS: { key: keyof Fields; type?: "number" | "date"; wide?: boolean; ltr?: boolean }[] = [
  { key: "invoice_number", ltr: true }, { key: "issue_date", type: "date", ltr: true },
  { key: "seller_name", wide: true }, { key: "seller_vat", ltr: true },
  { key: "due_date", type: "date", ltr: true }, { key: "buyer_name", wide: true }, { key: "buyer_vat", ltr: true },
  { key: "currency", ltr: true }, { key: "subtotal", type: "number", ltr: true }, { key: "vat_amount", type: "number", ltr: true },
  { key: "total", type: "number", ltr: true },
];

/** UBL tax category of a line. Lines without one are standard-rated. */
const VAT_CATEGORY = { S: tk("Standard rate"), Z: tk("Zero-rated"), E: tk("Exempt"), O: tk("Out of scope") };

export function Document({ run }: { run: Run }) {
  const { t } = useApp();
  const [url, setUrl] = useState<string | null>(null);
  const [text, setText] = useState<string | null>(null);
  useEffect(() => {
    let revoked: string | null = null;
    setUrl(null); setText(null);
    fileBlobUrl(`/runs/${run.id}/file`).then(async (u) => {
      revoked = u;
      if (run.content_type === "text/plain" || run.content_type === "application/xml") setText(await (await fetch(u)).text());
      else setUrl(u);
    }).catch(() => setText(t("Could not load the original file.")));
    return () => { if (revoked) URL.revokeObjectURL(revoked); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run.id, run.content_type]);
  return (
    <div className="doc">
      {/* the original may be Arabic, English or both: let it pick its own direction */}
      {text !== null && <pre dir="auto">{text}</pre>}
      {url && run.content_type === "application/pdf" && <iframe src={url} title={run.filename} />}
      {url && run.content_type.startsWith("image/") && <img src={url} alt={run.filename} />}
    </div>
  );
}

export function Evidence({ run }: { run: Run }) {
  const { t } = useApp();
  return (
    <div className="col" style={{ gap: 18 }}>
      <section>
        <h3 style={{ marginBottom: 6 }}>{t("Checks")}</h3>
        <div className="checks">
          {run.results.map((r) => (
            <div key={r.key}><CheckMark s={r.status} /><div>{t(r.name)}<small>{r.status === "pass" ? "" : <bdi dir="auto">{r.detail}</bdi>}{r.status === "fail" ? ` · ${r.severity === "reject" ? t("would reject") : t("sends to review")}` : ""}</small></div></div>
          ))}
          {!run.results.length && <p className="muted small">{t("No checks ran.")}</p>}
        </div>
      </section>
      <section>
        <h3 style={{ marginBottom: 6 }}>{t("Trace")}</h3>
        <div className="trace">
          {run.trace.map((s, i) => (
            <div key={i} className={s.ok ? "" : "bad"}><b>{t(s.step)}</b> <span className="muted small num">{s.ms ? t("{ms} ms", { ms: s.ms }) : ""}</span><div className="small muted" dir="auto">{s.detail}</div></div>
          ))}
        </div>
      </section>
      {run.extraction?.extractor && (
        <p className="muted small">
          {t("Read by {reader}", { reader: t(run.extraction.extractor) })}{run.extraction.model ? <> (<bdi dir="ltr">{run.extraction.model}</bdi>)</> : ""} · {t("confidence {pct}", { pct: pct(run.extraction.confidence) })}
          {run.extraction.tokens_in ? ` · ${t("{n} tokens", { n: run.extraction.tokens_in + run.extraction.tokens_out })}` : ""}
        </p>
      )}
      {run.extraction?.notes?.map((n, i) => <div key={i} className="notice warn" dir="auto">{t(n)}</div>)}
    </div>
  );
}

/** Editable fields + decision buttons. Used on the review screen. */
export function ReviewForm({ run, onDone }: { run: Run; onDone: (r: Run) => void }) {
  const { t, role, toast, refreshCounts } = useApp();
  const base = run.extracted ?? ({} as Fields);
  const [vals, setVals] = useState<Record<string, string>>({});
  const [note, setNote] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { setVals({}); setNote(""); setErr(null); }, [run.id]);
  const shown = (k: keyof Fields) => (k in vals ? vals[k] : base[k] == null ? "" : String(base[k]));
  const dirty = (k: keyof Fields) => k in vals && vals[k] !== (base[k] == null ? "" : String(base[k]));
  const canAct = can(role, "reviewer");

  async function decide(decision: "approve" | "reject") {
    setBusy(true); setErr(null);
    const edits: Record<string, unknown> = {};
    for (const f of EDIT_FIELDS) if (dirty(f.key)) edits[f.key] = vals[f.key];
    try {
      const out = await api<Run>(`/runs/${run.id}/review`, { method: "POST", body: { decision, note, edits } });
      toast(decision === "approve" ? t("Approved") : t("Rejected")); refreshCounts(-1); onDone(out);
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }
  useEffect(() => {
    if (!canAct) return;
    const h = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.key === "a") { e.preventDefault(); decide("approve"); }
      // preventDefault keeps the "r" itself from landing in the note once it has focus
      if (e.key === "r") { e.preventDefault(); (document.getElementById("reject-note") as HTMLTextAreaElement | null)?.focus(); }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run.id, vals, note, canAct]);

  return (
    <div className="col" style={{ gap: 14 }}>
      <div className="fieldgrid">
        {EDIT_FIELDS.map((f) => {
          const fc = run.extraction?.field_confidence?.[f.key as string];
          const empty = shown(f.key) === "";
          return (
            <label key={f.key} className={`f ${f.wide ? "wide" : ""} ${dirty(f.key) ? "edited" : ""}`}>
              <span>{t(FIELD_LABEL[f.key])}{f.type === "date" && <span className="hint"> (<bdi dir="ltr">YYYY-MM-DD</bdi>)</span>}</span>
              <input type="text" dir={f.ltr ? "ltr" : "auto"} inputMode={f.type === "number" ? "decimal" : undefined} value={shown(f.key)} disabled={!canAct}
                aria-invalid={empty} placeholder={empty ? t("Missing") : ""} onChange={(e) => setVals({ ...vals, [f.key]: e.target.value })} />
              {fc != null && <span className={`conf ${fc < 0.85 ? "low" : ""}`} title={t("confidence {pct}", { pct: pct(fc) })}><i style={{ width: `${fc * 100}%` }} /></span>}
            </label>
          );
        })}
      </div>
      {base.line_items && base.line_items.length > 0 && (
        <div className="tw"><table><thead><tr><th>{t("Item")}</th><th className="n">{t("Qty")}</th><th className="n">{t("Unit price")}</th><th className="n">{t("Line total")}</th><th>{t("VAT")}</th></tr></thead>
          <tbody>{base.line_items.map((l, i) => <tr key={i}><td>{l.description}</td><td className="n">{l.quantity == null ? "–" : num(l.quantity, Number.isInteger(l.quantity) ? 0 : 2)}</td><td className="n">{money(l.unit_price)}</td><td className="n">{money(l.line_total)}</td><td className="small">{t(VAT_CATEGORY[l.vat_category || "S"])}</td></tr>)}</tbody></table></div>
      )}
      <label className="f">{t("Note")} {" "}<span className="hint">{t("(required when rejecting)")}</span>
        <textarea id="reject-note" dir="auto" value={note} onChange={(e) => setNote(e.target.value)} disabled={!canAct} />
      </label>
      <Err msg={err} />
      <div className="row wrap">
        <button className="btn primary" disabled={!canAct || busy} onClick={() => decide("approve")}>{t("Approve")} <kbd>a</kbd></button>
        <button className="btn danger" disabled={!canAct || busy} onClick={() => decide("reject")}>{t("Reject")}</button>
        {!canAct && <span className="muted small">{t("Viewers can read but not decide. Sign in as reviewer.")}</span>}
      </div>
    </div>
  );
}

export function RunHeader({ run }: { run: Run }) {
  const { t } = useApp();
  return (
    <div className="row wrap">
      <StatusPill status={run.status} />
      <span className="muted small"><bdi dir="ltr">{run.filename}</bdi> · <bdi dir="ltr">#{run.id}</bdi> · {when(run.created_at)}</span>
      {run.decision_by && <span className="muted small">· {t("decided by {name}", { name: run.decision_by })}</span>}
    </div>
  );
}
