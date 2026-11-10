import { useEffect, useState, type ReactNode } from "react";
import { api, fileBlobUrl } from "../api";
import type { Fields, PoStatus, RunDetail as Run, TimelineEvent } from "../types";
import { reason } from "../reasons";
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

/** A UBL invoice laid out for reading, from GET /runs/{id}/invoice. */
export type InvoiceParty = { name: string | null; vat: string | null; address: string[] };
export type InvoiceLine = { description: string; quantity: number | null; unit_price: number | null; line_total: number | null;
  vat_category: "S" | "Z" | "E" | "O" | null; vat_rate: number | null };
export type UblView = {
  invoice_type: "standard" | "simplified" | null; invoice_number: string | null; issue_date: string | null; issue_time: string | null;
  due_date: string | null; currency: string | null; seller: InvoiceParty; buyer: InvoiceParty; lines: InvoiceLine[];
  subtotal: number | null; vat_amount: number | null; total: number | null; iban: string | null; po_number: string | null; qr_payload: string | null;
};

/** Codes, numbers and amounts read left to right inside Arabic text too. */
const Ltr = ({ children, className }: { children: ReactNode; className?: string }) => <bdi dir="ltr" className={className}>{children}</bdi>;
/** An IBAN in groups of four, as it is printed on paper. */
const ibanGroups = (iban: string) => iban.replace(/(.{4})(?=.)/g, "$1 ");

export function InvoiceView({ inv, source }: { inv: UblView; source: string | null }) {
  const { t } = useApp();
  const cur = inv.currency;
  const party = (title: string, p: InvoiceParty) => (
    <section className="inv-party">
      <h4>{title}</h4>
      <p className="inv-name" dir="auto">{p.name || "–"}</p>
      {p.vat && <p><span className="muted">{t("VAT number")} </span><Ltr className="num">{p.vat}</Ltr></p>}
      {p.address.map((line, i) => <p key={i} className="muted" dir="auto">{line}</p>)}
    </section>
  );
  const qr = decodeQr(inv.qr_payload);
  return (
    <article className="inv" tabIndex={0} aria-label={t("Invoice {number}", { number: inv.invoice_number || "–" })}>
      <header className="inv-head">
        <div>
          <h3 className="inv-title">{inv.invoice_type === "simplified" ? t("Simplified tax invoice") : t("Tax invoice")}</h3>
          <Ltr className="inv-no num">{inv.invoice_number || "–"}</Ltr>
        </div>
        <dl className="inv-meta">
          <div><dt>{t("Issue date")}</dt><dd><Ltr className="num">{inv.issue_date || "–"}{inv.issue_time ? ` ${inv.issue_time.slice(0, 5)}` : ""}</Ltr></dd></div>
          {inv.due_date && <div><dt>{t("Due date")}</dt><dd><Ltr className="num">{inv.due_date}</Ltr></dd></div>}
          {cur && <div><dt>{t("Currency")}</dt><dd><Ltr>{cur}</Ltr></dd></div>}
        </dl>
      </header>
      <div className="inv-parties">{party(t("Seller"), inv.seller)}{party(t("Buyer"), inv.buyer)}</div>
      <div className="inv-lines">
        <table>
          <caption className="sr-only">{t("Line items")}</caption>
          <thead><tr><th>{t("Description")}</th><th className="n">{t("Qty")}</th><th className="n">{t("Unit price")}</th><th>{t("VAT")}</th><th className="n">{t("Line total")}</th></tr></thead>
          <tbody>{inv.lines.map((l, i) => { const vat = VAT_CATEGORY[l.vat_category || "S"]; return (
            <tr key={i}>
              <td dir="auto">{l.description || "–"}</td>
              <td className="n"><Ltr>{num(l.quantity, Number.isInteger(l.quantity ?? 0) ? 0 : 2)}</Ltr></td>
              <td className="n"><Ltr>{money(l.unit_price)}</Ltr></td>
              <td>{t(vat)}{l.vat_rate != null && <span className="muted"> <Ltr>{`${num(l.vat_rate)}%`}</Ltr></span>}</td>
              <td className="n"><Ltr>{money(l.line_total)}</Ltr></td>
            </tr>
          ); })}</tbody>
        </table>
      </div>
      <dl className="inv-totals">
        <div><dt>{t("Subtotal")}</dt><dd><Ltr>{money(inv.subtotal, cur)}</Ltr></dd></div>
        <div><dt>{t("VAT")}</dt><dd><Ltr>{money(inv.vat_amount, cur)}</Ltr></dd></div>
        <div className="inv-total"><dt>{t("Total")}</dt><dd><Ltr>{money(inv.total, cur)}</Ltr></dd></div>
      </dl>
      {(inv.iban || inv.po_number) && (
        <dl className="inv-pay">
          {inv.iban && <div><dt>{t("IBAN")}</dt><dd><Ltr className="num">{ibanGroups(inv.iban)}</Ltr></dd></div>}
          {inv.po_number && <div><dt>{t("PO number")}</dt><dd><Ltr>{inv.po_number}</Ltr></dd></div>}
        </dl>
      )}
      {inv.qr_payload && (
        <section className="inv-qr">
          <h4>{t("QR code")}</h4>
          {qr ? <dl className="qr-list">{QR_TAGS.filter(([n]) => qr[n]).map(([n, label]) => <div key={n}><dt>{t(label)}</dt><dd dir="auto">{qr[n]}</dd></div>)}</dl>
            : <p className="muted">{t("The QR code could not be decoded.")}</p>}
          <p className="inv-payload" dir="ltr">{inv.qr_payload}</p>
        </section>
      )}
      {source !== null && (
        <details className="inv-src">
          <summary>{t("Show source XML")}</summary>
          <pre className="xml" dir="ltr" tabIndex={0} aria-label={t("Source XML")}>{source}</pre>
        </details>
      )}
    </article>
  );
}

export function Document({ run }: { run: Run }) {
  const { t } = useApp();
  const [url, setUrl] = useState<string | null>(null);
  const [text, setText] = useState<string | null>(null);
  const [inv, setInv] = useState<UblView | null>(null);
  const [failed, setFailed] = useState(false);
  const xml = run.content_type === "application/xml";
  useEffect(() => {
    let revoked: string | null = null, live = true;
    setUrl(null); setText(null); setInv(null); setFailed(false);
    if (xml) api<UblView>(`/runs/${run.id}/invoice`).then((v) => { if (live) setInv(v); }).catch(() => { if (live) setFailed(true); });
    fileBlobUrl(`/runs/${run.id}/file`).then(async (u) => {
      revoked = u;
      if (run.content_type === "text/plain") setText(await (await fetch(u)).text());
      else if (xml) setText(prettyXml(await (await fetch(u)).text()));
      else setUrl(u);
    }).catch(() => setText(t("Could not load the original file.")));
    return () => { live = false; if (revoked) URL.revokeObjectURL(revoked); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run.id, run.content_type]);
  return (
    <div className={xml && !failed ? "doc doc-inv" : "doc"}>
      {/* an XML invoice is shown as an invoice; its source only on request, or if the invoice view cannot be built */}
      {xml && inv && <InvoiceView inv={inv} source={text} />}
      {xml && failed && text !== null && <pre dir="ltr" className="xml">{text}</pre>}
      {/* the original may be Arabic, English or both: let it pick its own direction */}
      {!xml && text !== null && <pre dir="auto">{text}</pre>}
      {/* open a PDF at the pane's width, without the page sidebar that would shrink it; the viewer's toolbar stays */}
      {url && run.content_type === "application/pdf" && <iframe src={`${url}#navpanes=0&view=FitH`} title={run.filename} />}
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
      <h3 className="sec-title">{t("Vendor and purchase order")}</h3>
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
      {/* the server's own sentence; in Arabic it is translated when it is one of the known ones */}
      {vm && <Why text={vm.why} className="small muted vm-why" />}
      {po && po.status !== "no_po" && (
        <div className={`po-line ${PO_TONE[po.status]}`}>
          <b>{t(PO_STATUS[po.status], { po: po.po_number || "" })}</b>
          {po.po_amount != null && <span className="small">{t("PO amount")}: <bdi dir="ltr">{money(po.po_amount, po.po_currency)}</bdi>{po.amount != null && <> · {t("invoice")}: <bdi dir="ltr">{money(po.amount, po.po_currency)}</bdi></>}</span>}
        </div>
      )}
    </section>
  );
}

/** A reason the server wrote, in the reader's language when it is a known sentence (see reasons.ts). */
function Why({ text, className }: { text: string; className: string }) {
  const { t, lang } = useApp();
  const shown = reason(text, t, lang);
  return <p className={className}><bdi dir={shown === text ? "auto" : "rtl"}>{shown}</bdi></p>;
}

/** Failed checks first, high risk on top, each with its reason in plain words. Passed checks fold away. */
export function CheckList({ run }: { run: Run }) {
  const { t } = useApp();
  const rank = (r: Run["results"][number]) => (r.risk === "high" ? 0 : r.severity === "reject" ? 1 : 2);
  const failed = run.results.filter((r) => r.status === "fail").sort((a, b) => rank(a) - rank(b));
  const skipped = run.results.filter((r) => r.status === "skip");
  const passed = run.results.filter((r) => r.status === "pass");
  const row = (r: Run["results"][number]) => (
    <div key={r.key} className={`ck ck-${r.status}${r.risk === "high" ? " high-risk" : ""}`}>
      <CheckMark s={r.status} />
      <div className="ck-body">
        <div className="ck-name">
          <span>{t(r.name)}</span>
          {r.risk === "high" && <span className="pill risk-pill">{t("High risk")}</span>}
          {r.status === "fail" && <span className={`ck-effect ${r.severity === "reject" ? "reject" : "review"}`}>{r.severity === "reject" ? t("would reject") : t("sends to review")}</span>}
        </div>
        {r.status !== "pass" && r.detail && <Why text={r.detail} className="ck-why" />}
      </div>
    </div>
  );
  if (!run.results.length) return <p className="muted small">{t("No checks ran.")}</p>;
  return (
    <div className="checks">
      {failed.map(row)}
      {!failed.length && <p className="checks-clear">{t("No check failed.")}</p>}
      {skipped.map(row)}
      {passed.length > 0 && <details className="checks-passed"><summary>{t("Passed checks ({n})", { n: passed.length })}</summary>{passed.map(row)}</details>}
    </div>
  );
}

/** A name inside a translated sentence keeps its own direction (U+2068 first strong isolate, U+2069 pop). */
const own = (s: string) => `⁨${s}⁩`;
/** The reader's name for a sentence: the two built-in readers by what they are, an AI provider by its own name. */
const READER: Record<string, string> = { "rule-based": tk("the built-in reader"), "ubl-xml": tk("the XML reader") };
const readerName = (t: (s: string) => string, r: string | null | undefined) => (r && !READER[r] ? own(r) : t(READER[r || "rule-based"]));
const ROUTED = { approved: tk("Approved automatically"), needs_review: tk("Sent to a person for review"), rejected: tk("Rejected automatically") };

/** What happened to the invoice, in plain words, oldest first: received, read, checked, routed, then what people did. */
export function Timeline({ events }: { events: TimelineEvent[] }) {
  const { t, lang } = useApp();
  const list = (xs: string[]) => xs.join(lang === "ar" ? "، " : ", ");
  const item = (e: TimelineEvent): [string, ReactNode] => {
    switch (e.kind) {
      case "received": return ["", t("Received from {name}", { name: own(e.actor) })];
      case "read": return e.ok
        ? ["", <>{t("Read by {reader}", { reader: readerName(t, e.reader) })}{e.model && <> (<bdi dir="ltr">{e.model}</bdi>)</>}
            {e.confidence != null && <span className="muted"> · {t("confidence {pct}", { pct: pct(e.confidence) })}</span>}
            {e.fell_back && <div className="small muted">{t("The AI call failed, so the built-in reader was used instead")}</div>}</>]
        : ["warn", t("Could not be read automatically")];
      case "checked": return ["", <>{e.rules_version != null ? t("Checked with rules version {v}", { v: num(e.rules_version) }) : t("Checked")}
        {e.failed != null && <span className="muted"> · {t("{n} checks failed", { n: e.failed })}</span>}</>];
      case "routed": return [e.outcome === "approved" ? "ok" : e.outcome === "rejected" ? "x" : "warn",
        <>{t(ROUTED[e.outcome])}{e.auto_approve_off && <div className="small muted">{t("Auto-approve is switched off, so it went to review.")}</div>}</>];
      case "failed": return ["x", t("Processing failed")];
      case "reprocess": return ["", t("Read again at the request of {name}", { name: own(e.actor) })];
      case "vendor_link": return ["", t("{name} linked the seller to a vendor", { name: own(e.actor) })];
      case "reviewed": return [e.decision === "approve" ? "h" : "x", <>
        {e.decision === "approve" ? t("Approved by {name}", { name: own(e.actor) }) : t("Rejected by {name}", { name: own(e.actor) })}
        {e.edited.length > 0 && <div className="small">{t("Corrected: {fields}", { fields: list(e.edited.map((f) => t(FIELD_LABEL[f] || f))) })}</div>}
        {e.note && <div className="small muted" dir="auto">{e.note}</div>}</>];
    }
  };
  return (
    <ol className="trace tl">
      {events.map((e, i) => { const [tone, body] = item(e); return (
        <li key={i} className={tone}><div>{body}</div><time className="small muted" dateTime={e.at}>{when(e.at)}</time></li>
      ); })}
    </ol>
  );
}

export function Evidence({ run, onChange, checks = true }: { run: Run; onChange?: (r: Run) => void; checks?: boolean }) {
  const { t } = useApp();
  const qr = decodeQr((run.final_fields ?? run.extracted)?.qr_payload);
  return (
    <div className="col evidence">
      {checks && (
        <section>
          <h3 className="sec-title">{t("Checks")}</h3>
          <CheckList run={run} />
        </section>
      )}
      <VendorPanel run={run} onChange={onChange} />
      {qr && (
        <section>
          <h3 className="sec-title">{t("What the QR code says")}</h3>
          <dl className="qr-list">{QR_TAGS.filter(([n]) => qr[n]).map(([n, label]) => <div key={n}><dt>{t(label)}</dt><dd dir="auto">{qr[n]}</dd></div>)}</dl>
        </section>
      )}
      {run.timeline && run.timeline.length > 0 && (
        <section>
          <h3 className="sec-title">{t("Timeline")}</h3>
          <Timeline events={run.timeline} />
        </section>
      )}
      <details className="trace-more">
        <summary>{t("Technical trace")}</summary>
        <div className="trace">
          {run.trace.map((s, i) => (
            <div key={i} className={s.ok ? "" : "bad"}><b>{t(s.step)}</b> <span className="muted small num">{s.ms ? t("{ms} ms", { ms: s.ms }) : ""}</span><div className="small muted" dir="auto">{s.detail}</div></div>
          ))}
        </div>
      </details>
      {run.extraction?.extractor && (
        <p className="muted small">
          {t("Read by {reader}", { reader: readerName(t, run.extraction.extractor) })}{run.extraction.model ? <> (<bdi dir="ltr">{run.extraction.model}</bdi>)</> : ""} · {t("confidence {pct}", { pct: pct(run.extraction.confidence) })}
          {run.extraction.tokens_in ? ` · ${t("{n} tokens", { n: run.extraction.tokens_in + run.extraction.tokens_out })}` : ""}
        </p>
      )}
      {run.extraction?.notes?.map((n, i) => <div key={i} className="notice warn" dir="auto">{t(n)}</div>)}
    </div>
  );
}

/** Editable fields + decision buttons. Used on the review screen. */
export function ReviewForm({ run, onDone, children }: { run: Run; onDone: (r: Run) => void; children?: ReactNode }) {
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
    <>
      <section className="panel">
        <h2>{t("Fields read from the invoice")}</h2>
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
          <div className="tw lines" tabIndex={0} role="region" aria-label={t("Line items")}><table><thead><tr><th>{t("Item")}</th><th className="n">{t("Qty")}</th><th className="n">{t("Unit price")}</th><th className="n">{t("Line total")}</th><th>{t("VAT")}</th></tr></thead>
            <tbody>{base.line_items.map((l, i) => <tr key={i}><td>{l.description}</td><td className="n">{l.quantity == null ? "–" : num(l.quantity, Number.isInteger(l.quantity) ? 0 : 2)}</td><td className="n">{money(l.unit_price)}</td><td className="n">{money(l.line_total)}</td><td className="small">{t(VAT_CATEGORY[l.vat_category || "S"])}</td></tr>)}</tbody></table></div>
        )}
      </section>
      {children}
      {/* stays on screen while the reviewer scrolls through the fields and evidence */}
      <section className="decide" aria-label={t("Decision")}>
        <label className="f"><span>{t("Note")} <span className="hint">{t("(required when rejecting)")}</span></span>
          <textarea id="reject-note" dir="auto" rows={2} value={note} onChange={(e) => setNote(e.target.value)} disabled={!canAct} />
        </label>
        <Err msg={err} />
        <div className="decide-row">
          <button className="btn primary" disabled={!canAct || busy} onClick={() => decide("approve")}>{t("Approve")} <kbd>a</kbd></button>
          <button className="btn danger" disabled={!canAct || busy} onClick={() => decide("reject")}>{t("Reject")}</button>
          {!canAct && <span className="muted small">{t("Viewers can read but not decide. Sign in as reviewer.")}</span>}
          <span className="rq-keys">{t("Shortcuts")}: <kbd>j</kbd> {t("next")} · <kbd>k</kbd> {t("previous")} · <kbd>a</kbd> {t("approve")} · <kbd>r</kbd> {t("jump to note")}</span>
        </div>
      </section>
    </>
  );
}

export function RunHeader({ run }: { run: Run }) {
  const { t } = useApp();
  const f = run.final_fields ?? run.extracted;
  return (
    <div className="run-head">
      <div className="grow">
        <h2 className="run-title"><span className="cell-text" dir="auto">{f?.seller_name || run.filename}</span></h2>
        <div className="run-meta">
          <StatusPill status={run.status} />
          {f?.invoice_number && <bdi dir="ltr">{f.invoice_number}</bdi>}
          <bdi dir="ltr">{run.filename}</bdi>
          <bdi dir="ltr">#{run.id}</bdi>
          <span>{when(run.created_at)}</span>
          {run.decision_by && <span>{t("decided by {name}", { name: run.decision_by })}</span>}
        </div>
      </div>
      {f?.total != null && <div className="run-total"><b><bdi dir="ltr">{money(f.total, f.currency)}</bdi></b><span>{t("Total")}</span></div>}
    </div>
  );
}
