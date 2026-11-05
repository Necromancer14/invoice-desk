import { useEffect, useState } from "react";
import { api, fileBlobUrl } from "../api";
import type { Fields, RunDetail as Run } from "../types";
import { CheckMark, Err, StatusPill, can, money, pct, useApp, when } from "../common";

const EDIT_FIELDS: { key: keyof Fields; label: string; type?: "number"; wide?: boolean }[] = [
  { key: "invoice_number", label: "Invoice number" }, { key: "issue_date", label: "Issue date (YYYY-MM-DD)" },
  { key: "seller_name", label: "Seller", wide: true }, { key: "seller_vat", label: "Seller VAT number" },
  { key: "due_date", label: "Due date (YYYY-MM-DD)" }, { key: "buyer_name", label: "Buyer", wide: true }, { key: "buyer_vat", label: "Buyer VAT number" },
  { key: "currency", label: "Currency" }, { key: "subtotal", label: "Subtotal", type: "number" }, { key: "vat_amount", label: "VAT amount", type: "number" },
  { key: "total", label: "Total", type: "number" },
];

export function Document({ run }: { run: Run }) {
  const [url, setUrl] = useState<string | null>(null);
  const [text, setText] = useState<string | null>(null);
  useEffect(() => {
    let revoked: string | null = null;
    setUrl(null); setText(null);
    fileBlobUrl(`/runs/${run.id}/file`).then(async (u) => {
      revoked = u;
      if (run.content_type === "text/plain") setText(await (await fetch(u)).text());
      else setUrl(u);
    }).catch(() => setText("Could not load the original file."));
    return () => { if (revoked) URL.revokeObjectURL(revoked); };
  }, [run.id, run.content_type]);
  return (
    <div className="doc">
      {text !== null && <pre>{text}</pre>}
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
        <h3 style={{ marginBottom: 6 }}>Checks</h3>
        <div className="checks">
          {run.results.map((r) => (
            <div key={r.key}><CheckMark s={r.status} /><div>{r.name}<small>{r.status === "pass" ? "" : r.detail}{r.status === "fail" ? ` · ${t(r.severity === "reject" ? "would reject" : "sends to review")}` : ""}</small></div></div>
          ))}
          {!run.results.length && <p className="muted small">No checks ran.</p>}
        </div>
      </section>
      <section>
        <h3 style={{ marginBottom: 6 }}>Trace</h3>
        <div className="trace">
          {run.trace.map((s, i) => (
            <div key={i} className={s.ok ? "" : "bad"}><b>{s.step}</b> <span className="muted small num">{s.ms ? `${s.ms} ms` : ""}</span><div className="small muted">{s.detail}</div></div>
          ))}
        </div>
      </section>
      {run.extraction?.extractor && (
        <p className="muted small">
          Read by {run.extraction.extractor}{run.extraction.model ? ` (${run.extraction.model})` : ""} · confidence {pct(run.extraction.confidence)}
          {run.extraction.tokens_in ? ` · ${run.extraction.tokens_in + run.extraction.tokens_out} tokens` : ""}
        </p>
      )}
      {run.extraction?.notes?.map((n, i) => <div key={i} className="notice warn">{n}</div>)}
    </div>
  );
}

/** Editable fields + decision buttons. Used on the review screen. */
export function ReviewForm({ run, onDone }: { run: Run; onDone: (r: Run) => void }) {
  const { role, toast, refreshCounts } = useApp();
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
      toast(decision === "approve" ? "Approved" : "Rejected"); refreshCounts(); onDone(out);
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }
  useEffect(() => {
    if (!canAct) return;
    const h = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if (e.key === "a") decide("approve");
      if (e.key === "r") (document.getElementById("reject-note") as HTMLTextAreaElement | null)?.focus();
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
              {f.label}
              <input type="text" inputMode={f.type === "number" ? "decimal" : undefined} value={shown(f.key)} disabled={!canAct}
                aria-invalid={empty} placeholder={empty ? "Missing" : ""} onChange={(e) => setVals({ ...vals, [f.key]: e.target.value })} />
              {fc != null && <span className={`conf ${fc < 0.85 ? "low" : ""}`}><i style={{ width: `${fc * 100}%` }} /></span>}
            </label>
          );
        })}
      </div>
      {base.line_items && base.line_items.length > 0 && (
        <div className="tw"><table><thead><tr><th>Item</th><th className="n">Qty</th><th className="n">Unit price</th><th className="n">Line total</th></tr></thead>
          <tbody>{base.line_items.map((l, i) => <tr key={i}><td>{l.description}</td><td className="n">{l.quantity}</td><td className="n">{money(l.unit_price)}</td><td className="n">{money(l.line_total)}</td></tr>)}</tbody></table></div>
      )}
      <label className="f">Note {" "}<span className="hint">(required when rejecting)</span>
        <textarea id="reject-note" value={note} onChange={(e) => setNote(e.target.value)} disabled={!canAct} />
      </label>
      <Err msg={err} />
      <div className="row wrap">
        <button className="btn primary" disabled={!canAct || busy} onClick={() => decide("approve")}>Approve <kbd>a</kbd></button>
        <button className="btn danger" disabled={!canAct || busy} onClick={() => decide("reject")}>Reject</button>
        {!canAct && <span className="muted small">Viewers can read but not decide. Sign in as reviewer.</span>}
      </div>
    </div>
  );
}

export function RunHeader({ run }: { run: Run }) {
  return (
    <div className="row wrap">
      <StatusPill status={run.status} />
      <span className="muted small">{run.filename} · #{run.id} · {when(run.created_at)}</span>
      {run.decision_by && <span className="muted small">· decided by {run.decision_by}</span>}
    </div>
  );
}
