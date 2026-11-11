import { Fragment, useEffect, useState, type ReactNode } from "react";
import { api, session } from "../api";
import type { CopilotStep, Finding, Proposal, Recommendation, RunDetail } from "../types";
import { Err, FIELD_LABEL, can, money, num, pct, tk, useApp, when } from "../common";

/** What the copilot suggests, as a sentence and as a short word for the timeline. */
export const REC_LABEL: Record<Recommendation, string> = {
  approve: tk("Suggests approving"), reject: tk("Suggests rejecting"), hold: tk("Suggests finding out more before deciding"),
};
export const REC_SHORT: Record<Recommendation, string> = { approve: tk("approve"), reject: tk("reject"), hold: tk("find out more") };
const REC_TONE: Record<Recommendation, string> = { approve: "ok", reject: "err", hold: "warn" };
export const MODE_LABEL = { rules: tk("Rule-based"), gemini: tk("Gemini") };

const TOOL_LABEL: Record<string, string> = {
  get_invoice: tk("Opened the invoice"), find_vendor: tk("Looked up the vendor"), vendor_history: tk("Read the vendor's history"),
  iban_history: tk("Compared IBANs with earlier invoices"), get_po: tk("Looked up the purchase order"),
  similar_invoices: tk("Looked for similar earlier invoices"), reread: tk("Read the file again"), simulate_rule: tk("Tried a rule change (dry run)"),
};
const PO_STATUS: Record<string, string> = {
  found: tk("found"), not_found: tk("not found"), matched: tk("within the order"), over: tk("above the order"), closed: tk("closed"),
  vendor_mismatch: tk("belongs to another vendor"), currency_mismatch: tk("in another currency"), no_po: tk("no PO number"),
};

/** A name or number inside a translated sentence keeps its own direction. */
const own = (s: unknown) => `⁨${s ?? "–"}⁩`;
const RUNS = "\u0000";

/** Run numbers as links to the run, placed where the sentence has {runs}. */
function withRuns(text: string, runs: number[] | undefined, open: (id: number) => void): ReactNode {
  if (!text.includes(RUNS)) return text;
  const [before, after] = text.split(RUNS);
  return <>{before}{(runs ?? []).map((id, i) => <Fragment key={id}>{i > 0 && " "}<button className="linkish" onClick={() => open(id)}><bdi dir="ltr">#{id}</bdi></button></Fragment>)}{after}</>;
}

function FindingText({ f }: { f: Finding }) {
  const { t, lang, go } = useApp();
  const v = (k: string) => f[k] as never;
  const list = (xs: string[]) => xs.join(lang === "ar" ? "، " : ", ");
  const sar = (n: unknown) => (n == null ? "–" : money(n as number, "SAR"));
  const open = (id: number) => go("runs", String(id));
  let text: string;
  switch (f.code) {
    case "unreadable": text = t("The built-in reader could not read this invoice. Key the fields in from the original, or investigate with Gemini, which can read the file again."); break;
    case "missing_seller_vat": text = t("The seller VAT number is missing. A tax invoice needs it, so ask the vendor for a corrected invoice."); break;
    case "missing_fields": text = t("Fields missing: {fields}.", { fields: list(((f.fields as string[]) ?? []).map((x) => t(FIELD_LABEL[x] || x))) }); break;
    case "low_confidence": text = t("The reader was not sure of what it read (confidence {pct}). Compare the fields with the original.", { pct: pct(v("confidence")) }); break;
    case "iban_differs":
      text = t("The IBAN on the invoice (ending {inv}) is not the one in the vendor master (ending {master}). Confirm the change with the vendor through a contact you already hold before paying.", { inv: own(v("invoice_end")), master: own(v("master_end")) });
      if ((f.earlier_master as number) > 0) text += " " + t("{n} earlier invoices from this vendor used the IBAN in the vendor master.", { n: f.earlier_master as number });
      break;
    case "qr_disagrees": text = t("The QR code does not agree with the printed values. Ask the vendor for a corrected invoice."); break;
    case "date_problem": text = t("The issue date {date} is in the future or not a real date. Ask the vendor for a corrected invoice.", { date: own(v("date")) }); break;
    case "due_before_issue": text = t("The due date {due} is before the issue date {issue}. Ask the vendor for a corrected invoice.", { due: own(v("due")), issue: own(v("issue")) }); break;
    case "vendor_vat_differs": text = t("The seller VAT number on the invoice ({inv}) is not the one in the vendor master ({master}).", { inv: own(v("invoice_vat")), master: own(v("master_vat")) }); break;
    case "vendor_unknown": text = t("The seller is not in the vendor master. Check who they are and add them before deciding."); break;
    case "vendor_blocked": text = t("The vendor is blocked in the vendor master."); break;
    case "po_problem":
      text = f.status === "over"
        ? t("The invoice ({amount}) is above purchase order {po} ({po_amount}). Ask the buyer whether the order should change.", { amount: num(v("amount"), 2), po: own(v("po")), po_amount: num(v("po_amount"), 2) })
        : t("The invoice does not fit purchase order {po}: {status}.", { po: own(v("po")), status: t(PO_STATUS[f.status as string] || "not found") });
      break;
    case "negative_total": text = t("The total is negative. Check whether this is a credit note."); break;
    case "high_value":
      text = t("High value invoice: {total}.", { total: money(v("total"), v("currency")) }) + " " + ((f.earlier as number) > 0 && f.typical != null
        ? t("This vendor's usual approved invoice is about {typical}; the largest so far was {largest}.", { typical: sar(f.typical), largest: sar(f.largest) })
        : t("There are no earlier approved invoices from this vendor to compare with."));
      break;
    case "foreign_currency":
      text = f.matches_vendor ? t("In {currency}, the currency the vendor master holds for this vendor.", { currency: own(v("currency")) })
        : f.vendor_currency ? t("In {currency}, while the vendor master holds {vendor_currency} for this vendor.", { currency: own(v("currency")), vendor_currency: own(v("vendor_currency")) })
          : t("In {currency}.", { currency: own(v("currency")) });
      break;
    case "check_failed": text = t("Check failed: {name}.", { name: t(String(f.name)) }); break;
    case "possible_duplicate": text = t("An earlier invoice has the same seller and invoice number: {runs}.", { runs: RUNS }); break;
    case "same_total_before": text = t("An earlier invoice from this seller has the same total: {runs}. It may be sent twice.", { runs: RUNS }); break;
    case "instructions_in_document": text = t("The document contains text addressed to an AI. It was treated as data and changed nothing."); break;
    case "known_vendor": text = t("Known vendor {vendor}. Earlier invoices: {n}, approved {approved}, rejected {rejected}.", { vendor: own((lang === "ar" && f.vendor_ar) || f.vendor), n: num(v("earlier")), approved: num(v("approved")), rejected: num(v("rejected")) })
      + ((f.runs as number[])?.length ? " " + t("Latest: {runs}", { runs: RUNS }) : ""); break;
    case "no_vendor_master": text = t("The vendor master is empty, so who sent this cannot be confirmed."); break;
    case "vendor_not_confirmed": text = t("Nothing else failed, but the vendor could not be confirmed in the vendor master."); break;
    case "could_not_open": text = t("The invoice could not be opened."); break;
    case "step_limit": text = t("The copilot used its {n} steps without reaching a suggestion. Look at the steps, or try again.", { n: num(v("limit")) }); break;
    default: text = f.code;
  }
  return <>{withRuns(text, f.runs, open)}</>;
}

function StepText({ s }: { s: CopilotStep }) {
  const { t, lang } = useApp();
  const r = s.result;
  const v = (k: string) => r[k] as never;
  const list = (xs: string[]) => xs.join(lang === "ar" ? "، " : ", ");
  let what: string;
  switch (r.code) {
    case "invoice": what = t("{n} checks failed", { n: v("failed") }) + (r.flagged ? " · " + t("text addressed to an AI found, treated as data") : ""); break;
    case "vendor_found": what = t("found {name}", { name: own((lang === "ar" && r.name_ar) || r.name) }); break;
    case "vendor_not_found": what = t("no vendor matched"); break;
    case "history": what = t("earlier invoices: {n}, approved {approved}, rejected {rejected}", { n: num(v("count")), approved: num(v("approved")), rejected: num(v("rejected")) }); break;
    case "ibans": {
      const used = (r.used as { end: string; count: number }[]) ?? [];
      what = t("vendor master IBAN ends {master}", { master: own(r.master ?? "–") }) + " · " + (used.length
        ? t("earlier invoices used: {ibans}", { ibans: list(used.map((u) => `${own(`…${u.end}`)} ×${num(u.count)}`)) })
        : t("no IBAN on earlier invoices"));
      break;
    }
    case "po": what = t("Purchase order {number}: {status}", { number: own(v("number")), status: t(PO_STATUS[r.status as string] || "not found") }); break;
    case "similar": what = t("similar earlier invoices: {n}", { n: num(v("count")) }); break;
    case "reread": what = t("fields that differ: {n}", { n: num(v("differences")) }); break;
    case "simulated": what = t("{changed} of {checked} past decisions would change", { changed: num(v("changed")), checked: num(v("checked")) }); break;
    case "error": return <><span>{TOOL_LABEL[s.tool] ? t(TOOL_LABEL[s.tool]) : t("Asked for {tool}", { tool: own(s.tool) })}</span>
      <div className="small cp-err">{t("Not done:")} <span dir="auto">{String(r.message ?? "")}</span></div></>;
    default: what = r.code;
  }
  return <><span>{TOOL_LABEL[s.tool] ? t(TOOL_LABEL[s.tool]) : s.tool}</span><div className="small muted">{what}</div></>;
}

/** The review copilot panel: what it suggests, why, and the steps it took. The reviewer still decides. */
export default function Copilot({ run, onRun }: { run: RunDetail; onRun?: (r: RunDetail) => void }) {
  const { t, lang, role, toast } = useApp();
  const [list, setList] = useState<Proposal[] | null>(null);
  const [busy, setBusy] = useState<"rules" | "ai" | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    setList(null); setErr(null);
    api<Proposal[]>(`/runs/${run.id}/proposals`).then((x) => { if (live) setList(x); }).catch((e) => { if (live) setErr((e as Error).message); });
    return () => { live = false; };
  }, [run.id]);
  const p = list?.[0];
  const canAct = can(role, "reviewer") && run.status === "needs_review";
  const gemini = session.provider === "gemini" && session.aiReady();

  async function go(mode: "rules" | "ai") {
    setBusy(mode); setErr(null);
    try {
      const out = await api<Proposal>(`/runs/${run.id}/investigate`, { body: { mode }, ai: mode === "ai" });
      setList((l) => [out, ...(l ?? [])]);
      toast(t("The copilot has a suggestion"));
      if (onRun) api<RunDetail>(`/runs/${run.id}`).then(onRun).catch(() => { /* the timeline refreshes on the next open */ });
    } catch (e) { setErr((e as Error).message); } finally { setBusy(null); }
  }

  const summary = p?.summary ? (lang === "ar" ? p.summary.ar || p.summary.en : p.summary.en || p.summary.ar) : "";
  return (
    <section className="panel copilot col" aria-labelledby="copilot-h" aria-busy={busy != null}>
      <div className="row wrap cp-head">
        <h2 id="copilot-h">{t("Review copilot")}</h2>
        {p && <span className="pill cp-mode">{t(MODE_LABEL[p.mode])}{p.model && <> · <bdi dir="ltr">{p.model}</bdi></>}</span>}
      </div>
      <p className="muted small">{t("It looks things up and suggests. It cannot approve or reject; you decide.")}</p>
      {p && (
        <>
          <div className={`notice ${REC_TONE[p.recommendation]} cp-rec`} role="status"><b>{t(REC_LABEL[p.recommendation])}</b></div>
          {summary && <p className="cp-summary" dir="auto">{summary}</p>}
          {p.findings.length > 0 && <ul className="cp-findings">{p.findings.map((f, i) => <li key={i} className={`e-${f.effect}`}><FindingText f={f} /></li>)}</ul>}
          {p.evidence.length > 0 && (
            <div><h3 className="sec-title">{t("Evidence it gave")}</h3><ul className="cp-findings">{p.evidence.map((e, i) => <li key={i} dir="auto">{e}</li>)}</ul></div>
          )}
          <details className="cp-steps">
            <summary>{t("Steps it took ({n})", { n: p.steps.length })}</summary>
            <ol className="trace tl">{p.steps.map((s) => <li key={s.n} className={s.ok ? "" : "warn"}><div><StepText s={s} /></div></li>)}</ol>
          </details>
          <p className="muted small">
            {[when(p.created_at), t("asked by {name}", { name: own(p.requested_by) }),
              p.mode === "gemini" ? t("{a} tokens in, {b} out", { a: num(p.tokens_in), b: num(p.tokens_out) }) : ""].filter(Boolean).join(" · ")}
          </p>
        </>
      )}
      {list && !p && <p className="small">{t("No suggestion yet for this invoice.")}</p>}
      {canAct && (
        <div className="row wrap">
          <button className="btn" disabled={busy != null} onClick={() => go("rules")}>{busy === "rules" ? t("Investigating…") : p ? t("Investigate again") : t("Investigate")}</button>
          {gemini && <button className="btn" disabled={busy != null} onClick={() => go("ai")}>{busy === "ai" ? t("Investigating…") : t("Investigate with Gemini")}</button>}
        </div>
      )}
      {canAct && !gemini && <p className="muted small">{t("Investigate uses fixed checks and needs no key. With a Gemini key in Settings, Gemini can investigate too.")}</p>}
      <Err msg={err} />
    </section>
  );
}
