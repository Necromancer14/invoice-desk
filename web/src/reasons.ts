/**
 * The reasons the server writes under a check and for a vendor match, as templates, so the portal can show them
 * in Arabic. The server builds them in rules.py (run_rules and the r_* rules), vendors.py (iban_problem,
 * VendorBook.match, po_match) and default_rules.py (messages). tests/test_reasons.py reads REASONS and MESSAGES
 * from this file and fails when the server can write a sentence none of them covers, so keep them in step.
 *
 * Order matters: a template is tried before the ones after it, so put the specific before the general.
 * Placeholders: {field} is a field id and {fields} a comma list of them (both shown by their label), {what} is
 * what a vendor matched on, {problem} and {detail} are reasons themselves; any other value is kept as written,
 * isolated so it keeps its own direction.
 */
import { tk, type Lang } from "./i18n";
import { FIELD_LABEL } from "./common";

export const REASONS = [
  // what is wrong with an IBAN (also inside the IBAN rule's reason); before "{field} is empty"
  tk("it is empty"),
  tk("it is not in IBAN form (two letters, two check digits, then the account)"),
  tk("a Saudi IBAN has 24 characters: SA, 2 check digits and 20 digits"),
  tk("its check digits do not match (mod-97)"),
  // required fields, patterns, VAT number format
  tk("missing: {fields}"),
  tk("{field} '{value}' must be 15 digits starting and ending with 3"),
  tk("{field} '{value}' does not match {pattern}"),
  tk("{field} '{value}' is not a date"),
  tk("{field} is empty"),
  // VAT, totals, line arithmetic
  tk("a standard-rated line has no amount"),
  tk("VAT is {vat} but {rate}% of the standard-rated {taxable} is {expected} (zero-rated and exempt lines carry no VAT)"),
  tk("subtotal or VAT amount missing"),
  tk("VAT is {vat} but {rate}% of {subtotal} is {expected}"),
  tk("line items add up to {sum} but subtotal is {subtotal}"),
  tk("subtotal {subtotal} + VAT {vat} is {sum} but total is {total}"),
  tk("amounts missing"),
  tk("line {n}: {qty} x {price} is {product}, not {total}"),
  tk("no line items"),
  // dates, currency, amount limits
  tk("a date is missing"),
  tk("currency missing"),
  tk("currency {value} not in {allowed}"),
  tk("{field} {date} is in the future"),
  tk("{field} {date} is older than {days} days"),
  tk("{field} {date} is before {other}"),
  tk("{field} {value} is below {min}"),
  tk("{field} {value} exceeds {max}"),
  tk("{field} missing"),
  // QR code
  tk("no QR payload"),
  tk("QR payload is not valid TLV base64"),
  tk("QR VAT {qr} vs printed {printed}"),
  tk("QR date {qr} vs printed issue date {printed}"),
  tk("QR seller name differs from printed name"),
  tk("QR {field} {qr} vs printed {printed}"),
  tk("no QR code found (on a photo taken at an angle a QR code may be present but unreadable)"),
  // vendor master
  tk("no vendors in the vendor master yet"),
  tk("seller name and VAT number missing"),
  tk("vendor not identified"),
  tk("{name} is blocked in the vendor master"),
  tk("no VAT number to compare"),
  tk("the invoice says {invoice}, the vendor master says {master}"),
  tk("no IBAN on the invoice"),
  tk("High risk: the IBAN on the invoice is not valid ({problem})"),
  tk("no IBAN in the vendor master to compare"),
  tk("High risk: the invoice asks for payment to {invoice}, but the vendor master has {master}. A changed bank account is a common fraud pattern: confirm it with the vendor using contact details you already hold, not ones on this invoice."),
  tk("Seller \"{seller}\" matches exactly after normalising the {what} \"{written}\" ({key})."),
  tk("Seller \"{seller}\" is close (score {score}, at least {min} needed) the {what} \"{written}\" ({key})."),
  tk("No name matched well enough; the seller VAT number {vat} is this vendor's."),
  tk("\"{seller}\" is not in the vendor master; the closest is \"{name}\" at {score}."),
  tk("\"{seller}\" is not in the vendor master."),
  // purchase orders
  tk("no PO number on the invoice"),
  tk("The invoice gives no PO number."),
  tk("PO {po} is not among the purchase orders."),
  tk("PO {po} is not among the purchase orders"),
  tk("PO {po} belongs to {vendor}, not this vendor."),
  tk("The invoice is in {cur}, PO {po} in {po_cur}."),
  tk("The invoice {field} {amount} is above PO {po} ({po_amount}, tolerance {tol})."),
  tk("PO {po} is closed."),
  tk("Within PO {po} ({amount} {cur})."),
  // duplicates, confidence, custom expressions
  tk("seller VAT or invoice number missing"),
  tk("invoice {number} from {vat} was already received"),
  tk("extraction confidence {value} below {threshold}"),
  tk("could not evaluate, a field it needs is missing or the wrong type"),
  tk("condition not met: {expr}"),
  tk("rule error: {error}"),
];

/** The default rule set's messages; a failing rule's detail becomes "message (detail)". */
export const MESSAGES = [
  tk("A person needs to fill in the missing fields"), tk("Not a valid Saudi VAT number"), tk("Wrong VAT amount"),
  tk("Amounts do not add up"), tk("Foreign currency invoice"), tk("High value invoice"),
  tk("Negative total: check whether this is a credit note"), tk("Warning: no QR code was found"), tk("Unknown vendor"),
  tk("Blocked vendor"), tk("Above the PO amount"),
];
const WRAP = tk("{message} ({detail})");

const MATCHED_ON: Record<string, string> = { "English name": tk("English name"), "Arabic name": tk("Arabic name"), "linked name": tk("linked name"), "VAT number": tk("VAT number") };
const FIELD = "[a-z_]+";
const GROUP: Record<string, string> = { field: `(${FIELD})`, fields: `(${FIELD}(?:, ${FIELD})*)`, what: `(${Object.keys(MATCHED_ON).join("|")})` };
// a value never spans "; ", which joins several problems into one line
const ANY = "((?:(?!; ).)+?)";
const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

const COMPILED = REASONS.map((tpl) => {
  const names: string[] = [];
  const src = tpl.split(/(\{\w+\})/).map((part) => {
    const m = /^\{(\w+)\}$/.exec(part);
    if (!m) return esc(part);
    names.push(m[1]);
    return GROUP[m[1]] ?? ANY;
  }).join("");
  return { tpl, names, re: new RegExp(`^${src}$`) };
});

type T = (key: string, vars?: Record<string, string | number>) => string;
const isolate = (s: string) => `⁨${s}⁩`;

/** The reason in the reader's language, or null when no template covers it. */
function translate(text: string, t: T): string | null {
  for (const { tpl, names, re } of COMPILED) {
    const m = re.exec(text);
    if (!m) continue;
    const vars: Record<string, string> = {};
    names.forEach((name, i) => {
      const v = m[i + 1];
      if (name === "field") vars[name] = t(FIELD_LABEL[v] ?? v);
      else if (name === "fields") vars[name] = v.split(", ").map((f) => t(FIELD_LABEL[f] ?? f)).join("، ");
      else if (name === "what") vars[name] = t(MATCHED_ON[v]);
      else if (name === "problem") vars[name] = translate(v, t) ?? isolate(v);
      else vars[name] = isolate(v);
    });
    return t(tpl, vars);
  }
  // a rule's message around its detail: "Wrong VAT amount (VAT is ...)"
  const w = /^(.+?) \((.*)\)$/.exec(text);
  if (w) {
    const detail = translate(w[2], t);
    if (detail !== null) return t(WRAP, { message: MESSAGES.includes(w[1]) ? t(w[1]) : isolate(w[1]), detail });
  }
  // several problems in one line
  if (text.includes("; ")) {
    const parts = text.split("; ").map((p) => translate(p, t));
    if (parts.every((p) => p !== null)) return parts.join("؛ ");
  }
  return null;
}

/** A server-written reason for the reader. English is shown as sent; in Arabic anything unknown is shown as sent. */
export function reason(text: string, t: T, lang: Lang): string {
  if (lang === "en" || !text) return text;
  return translate(text, t) ?? text;
}
