import { useEffect, useState } from "react";
import { api, fileBlobUrl } from "../api";
import type { Fields, PoStatus, RunDetail as Run } from "../types";
import { CheckMark, Err, FIELD_LABEL, StatusPill, can, money, num, pct, tk, useApp, when } from "../common";

/** ltr: codes, dates and amounts, typed and shown left-to-right even in Arabic. Labels come from FIELD_LABEL. */
const EDIT_FIELDS: { key: keyof Fields; type?: "number" | "date"; wide?: boolean; ltr?: boolean }[] = [
  { key: "invoice_number", ltr: true }, { key: "issue_date", type: "date", ltr: true },
  { key: "seller_name", wide: true }, { key: "seller_vat", ltr: true },
  { key: "due_date", type: "date", ltr: true }, { key: "buyer_name", wide: true }, { key: "buyer_vat", ltr: true },
  { key: "currency", ltr: true }, { key: "subtotal", type: "number", ltr: true }, { key: "vat_amount", type: "number", ltr: true },
  { key: "total", type: "number", ltr: true }, { key: "iban", wide: true, ltr: true }, { key: "po_number", ltr: true },
];

/** UBL tax category of a line. Lines without one are standard-rated. */
const VAT_CATEGORY = { S: tk("Standard rate"), Z: tk("Zero-rated"), E: tk("Exempt"), O: tk("Out of scope") };

/** Indents an XML document for reading, two spaces a level; an element holding only text stays on one line.
 *  If the XML cannot be parsed the original text is shown unchanged. */
export function prettyXml(src: string): string {
  const doc = new DOMParser().parseFromString(src, "application/xml");
  if (doc.getElementsByTagName("parsererror").length) return src;
  const esc = (v: string) => v.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const attrs = (el: Element) => [...el.attributes].map((a) => ` ${a.name}="${esc(a.value).replace(/"/g, "&quot;")}"`).join("");
  const out: string[] = [];
  const decl = src.match(/^\s*<\?xml[^>]*\?>/);
  if (decl) out.push(decl[0].trim());
  const walk = (el: Element, depth: number) => {
    const pad = "  ".repeat(depth);
    const kids = [...el.childNodes].filter((n) => n.nodeType === 1 || n.nodeType === 8 || (n.nodeType === 3 && n.textContent!.trim()));
    if (!kids.length) { out.push(`${pad}<${el.tagName}${attrs(el)}/>`); return; }
    if (kids.every((n) => n.nodeType === 3)) { out.push(`${pad}<${el.tagName}${attrs(el)}>${esc(el.textContent!.trim())}</${el.tagName}>`); return; }
    out.push(`${pad}<${el.tagName}${attrs(el)}>`);
    for (const n of kids) {
      if (n.nodeType === 1) walk(n as Element, depth + 1);
      else if (n.nodeType === 8) out.push(`${pad}  <!--${n.textContent}-->`);
      else out.push(`${pad}  ${esc(n.textContent!.trim())}`);
    }
    out.push(`${pad}</${el.tagName}>`);
  };
  walk(doc.documentElement, 0);
  return out.join("\n");
}

export function Document({ run }: { run: Run }) {
  const { t } = useApp();
  const [url, setUrl] = useState<string | null>(null);
  const [text, setText] = useState<string | null>(null);
  useEffect(() => {
    let revoked: string | null = null;
    setUrl(null); setText(null);
    fileBlobUrl(`/runs/${run.id}/file`).then(async (u) => {
      revoked = u;
      if (run.content_type === "text/plain") setText(await (await fetch(u)).text());
      else if (run.content_type === "application/xml") setText(prettyXml(await (await fetch(u)).text()));
      else setUrl(u);
    }).catch(() => setText(t("Could not load the original file.")));
    return () => { if (revoked) URL.revokeObjectURL(revoked); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run.id, run.content_type]);
  return (
    <div className="doc">
      {/* the original may be Arabic, English or both: let it pick its own direction. XML is code: always left-to-right */}
      {text !== null && <pre dir={run.content_type === "application/xml" ? "ltr" : "auto"} className={run.content_type === "application/xml" ? "xml" : undefined}>{text}</pre>}
      {url && run.content_type === "application/pdf" && <iframe src={url} title={run.filename} />}
      {url && run.content_type.startsWith("image/") && <img src={url} alt={run.filename} />}
    </div>
  );
}

/** The ZATCA-style QR payload: base64 of tag-length-value fields (1 seller, 2 VAT number, 3 time stamp, 4 total, 5 VAT). */
function decodeQr(payload: string | null | undefined): Record<number, string> | null {
  if (!payload) return null;
  try {
    const raw = Uint8Array.from(atob(payload.trim()), (c) => c.charCodeAt(0));
    const out: Record<number, string> = {};
    for (let i = 0; i + 2 <= raw.length;) {
      const tag = raw[i], len = raw[i + 1];
      if (i + 2 + len > raw.length) return null;
      out[tag] = new TextDecoder().decode(raw.slice(i + 2, i + 2 + len));
      i += 2 + len;
    }
    return Object.keys(out).length ? out : null;
  } catch { return null; }
}
const QR_TAGS: [number, string][] = [[1, tk("Seller")], [2, tk("Seller VAT number")], [3, tk("Time stamp")], [4, tk("Total")], [5, tk("VAT amount")]];

const MATCHED_ON = { "English name": tk("English name"), "Arabic name": tk("Arabic name"), "linked name": tk("linked name"), "VAT number": tk("VAT number") };
const PO_STATUS: Record<PoStatus, string> = {
  no_po: tk("The invoice gives no PO number"), not_found: tk("PO {po} is not among the purchase orders"),
  vendor_mismatch: tk("PO {po} belongs to another vendor"), currency_mismatch: tk("PO {po} is in another currency"),
  closed: tk("PO {po} is closed"), over: tk("Above PO {po}"), matched: tk("Within PO {po}"),
};
const PO_TONE: Record<PoStatus, string> = { no_po: "", not_found: "warn", vendor_mismatch: "warn", currency_mismatch: "warn", closed: "warn", over: "err", matched: "ok" };

/** Which vendor the invoice was matched to, how closely and on what, plus its purchase order.
 *  Reviewers can link an unmatched seller name to a vendor; the run's checks are then run again. */
function VendorPanel({ run, onChange }: { run: Run; onChange?: (r: Run) => void }) {
  const { t, role, toast } = useApp();
  const [busy, setBusy] = useState(false);
  const vm = run.vendor_match, po = run.po_match;
  if (!vm && (!po || po.status === "no_po")) return null;
  const name = (v: { name_en: string | null; name_ar: string | null }) => v.name_en || v.name_ar || "";
  const canLink = onChange && can(role, "reviewer") && run.status === "needs_review" && !!(run.final_fields ?? run.extracted)?.seller_name;
  async function link(id: number) {
    setBusy(true);
    try { const r = await api<Run>(`/runs/${run.id}/link-vendor`, { body: { vendor_id: id } }); toast(t("Linked. The checks were run again.")); onChange!(r); }
    catch (e) { toast((e as Error).message, "err"); } finally { setBusy(false); }
  }
  return (
    <section>
      <h3 style={{ marginBottom: 6 }}>{t("Vendor and purchase order")}</h3>
      {vm && (vm.vendor ? (
        <div className="vm">
          <div className="row wrap" style={{ gap: 8 }}>
            <b className="cell-text" dir="auto">{name(vm.vendor)}</b>
            {vm.vendor.status === "blocked" && <span className="pill s-rejected">{t("Blocked")}</span>}
            <span className="pill s-approved">{t("match {pct}", { pct: pct(vm.score) })}</span>
          </div>
          <div className="small muted">{t("Matched on the {what}", { what: t(MATCHED_ON[vm.matched_on!] || vm.matched_on || "") })}</div>
        </div>
      ) : (
        <div className="vm">
          <div className="notice warn">{t("No vendor in the vendor master matches this seller well enough.")}</div>
          {vm.suggestions.length > 0 && <ul className="vm-sugg">{vm.suggestions.map((s) => (
            <li key={s.id}>
              <span className="cell-text" dir="auto">{name(s)}</span>
              <span className="muted small num">{t("match {pct}", { pct: pct(s.score) })}</span>
              {canLink && <button className="btn small" disabled={busy} onClick={() => link(s.id)}>{t("Link to vendor")}<span className="sr-only">: {name(s)}</span></button>}
            </li>
          ))}</ul>}
        </div>
      ))}
      {/* the explanation is the server's own sentence, in English, with the names as written */}
      {vm && <p className="small muted" style={{ margin: "4px 0 0" }}><bdi dir="auto">{vm.why}</bdi></p>}
      {po && po.status !== "no_po" && (
        <div className={`po-line ${PO_TONE[po.status]}`}>
          <b>{t(PO_STATUS[po.status], { po: po.po_number || "" })}</b>
          {po.po_amount != null && <span className="small">{t("PO amount")}: <bdi dir="ltr">{money(po.po_amount, po.po_currency)}</bdi>{po.amount != null && <> · {t("invoice")}: <bdi dir="ltr">{money(po.amount, po.po_currency)}</bdi></>}</span>}
        </div>
      )}
    </section>
  );
}

export function Evidence({ run, onChange }: { run: Run; onChange?: (r: Run) => void }) {
  const { t } = useApp();
  const qr = decodeQr((run.final_fields ?? run.extracted)?.qr_payload);
  return (
    <div className="col" style={{ gap: 18 }}>
      <VendorPanel run={run} onChange={onChange} />
      {qr && (
        <section>
          <h3 style={{ marginBottom: 6 }}>{t("What the QR code says")}</h3>
          <dl className="qr-list">{QR_TAGS.filter(([n]) => qr[n]).map(([n, label]) => <div key={n}><dt>{t(label)}</dt><dd dir="auto">{qr[n]}</dd></div>)}</dl>
        </section>
      )}
      <section>
        <h3 style={{ marginBottom: 6 }}>{t("Checks")}</h3>
        <div className="checks">
          {run.results.map((r) => (
            <div key={r.key} className={r.risk === "high" ? "high-risk" : undefined}><CheckMark s={r.status} /><div>{t(r.name)}{r.risk === "high" && <span className="pill s-rejected risk-pill">{t("High risk")}</span>}<small>{r.status === "pass" ? "" : <bdi dir="auto">{r.detail}</bdi>}{r.status === "fail" ? ` · ${r.severity === "reject" ? t("would reject") : t("sends to review")}` : ""}</small></div></div>
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
