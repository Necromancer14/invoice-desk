import { useRef, useState } from "react";
import { api } from "../api";
import type { ImportResult, PurchaseOrder, Vendor } from "../types";
import { Empty, Err, Head, Modal, can, money, tk, useApp, useLoad } from "../common";

const STATUS = { approved: tk("Approved"), blocked: tk("Blocked") };
const PO_STATUS = { open: tk("Open"), closed: tk("Closed") };
const BLANK = { name_en: "", name_ar: "", vat: "", iban: "", currency: "SAR", status: "approved" as Vendor["status"] };

/** IBAN in groups of four for reading, as banks print it. */
const ibanText = (v: string | null) => (v ? v.replace(/(.{4})(?=.)/g, "$1 ") : "–");

/** A CSV upload button. The server reads the file; rows with problems are reported back by row number. */
function CsvImport({ path, label, onDone }: { path: string; label: string; onDone: () => void }) {
  const { t, toast } = useApp();
  const input = useRef<HTMLInputElement>(null);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  async function upload(f: File | undefined) {
    if (!f) return;
    setErr(null); setResult(null);
    const form = new FormData(); form.append("file", f);
    try {
      const r = await api<ImportResult>(path, { form });
      setResult(r); onDone();
      toast(t("{added} added, {updated} updated", { added: r.added, updated: r.updated }));
    } catch (e) { setErr((e as Error).message); } finally { if (input.current) input.current.value = ""; }
  }
  return (
    <>
      <label className="btn">
        {label}
        <input ref={input} type="file" accept=".csv,text/csv" className="sr-only" onChange={(e) => upload(e.target.files?.[0])} />
      </label>
      <Err msg={err} />
      {result && result.error_count > 0 && (
        <div className="notice warn" style={{ flexBasis: "100%" }}>
          {t("{n} rows were not imported", { n: result.error_count })}
          {/* the problems come from the server in English and point at CSV rows, so they stay as written */}
          <ul className="small" style={{ margin: "6px 0 0" }}>{result.errors.map((e) => <li key={e.row}>{t("Row {n}", { n: e.row })}: <bdi dir="ltr">{e.message}</bdi></li>)}</ul>
        </div>
      )}
    </>
  );
}

function VendorForm({ vendor, onClose, onSaved }: { vendor: Vendor | null; onClose: () => void; onSaved: () => void }) {
  const { t, toast } = useApp();
  const [v, setV] = useState(vendor ? { ...BLANK, ...Object.fromEntries(Object.entries(vendor).map(([k, x]) => [k, x ?? ""])) } : BLANK);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof BLANK) => (e: { target: { value: string } }) => setV({ ...v, [k]: e.target.value });
  async function save() {
    setBusy(true); setErr(null);
    const body = { name_en: v.name_en, name_ar: v.name_ar, vat: v.vat, iban: v.iban, currency: v.currency, status: v.status };
    try {
      await api(vendor ? `/vendors/${vendor.id}` : "/vendors", { method: vendor ? "PUT" : "POST", body });
      toast(t("Vendor saved")); onSaved(); onClose();
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }
  return (
    <Modal title={vendor ? t("Edit vendor") : t("Add vendor")} onClose={onClose}>
      <div className="fieldgrid">
        <label className="f wide"><span>{t("Name in English")}</span><input dir="ltr" value={v.name_en} onChange={set("name_en")} /></label>
        <label className="f wide"><span>{t("Name in Arabic")}</span><input dir="rtl" lang="ar" value={v.name_ar} onChange={set("name_ar")} /></label>
        <label className="f"><span>{t("VAT number")}</span><input dir="ltr" inputMode="numeric" value={v.vat} onChange={set("vat")} /></label>
        <label className="f"><span>{t("Default currency")}</span><input dir="ltr" maxLength={3} value={v.currency} onChange={set("currency")} /></label>
        <label className="f wide"><span>{t("IBAN")} <span className="hint">({t("Saudi IBANs have 24 characters and start with SA")})</span></span><input dir="ltr" value={v.iban} onChange={set("iban")} /></label>
        <label className="f"><span>{t("Status")}</span>
          <select value={v.status} onChange={set("status")}>{Object.entries(STATUS).map(([k, l]) => <option key={k} value={k}>{t(l)}</option>)}</select>
        </label>
      </div>
      <p className="muted small">{t("The VAT number and IBAN are checked for their format and check digits only. Nothing is looked up with ZATCA or a bank.")}</p>
      <Err msg={err} />
      <div className="row">
        <button className="btn primary" disabled={busy} onClick={save}>{t("Save")}</button>
        <button className="btn" onClick={onClose}>{t("Cancel")}</button>
      </div>
    </Modal>
  );
}

export default function Vendors() {
  const { t, role, toast } = useApp();
  const admin = can(role, "admin");
  const vendors = useLoad(() => api<Vendor[]>("/vendors"), []);
  const pos = useLoad(() => api<PurchaseOrder[]>("/purchase-orders"), []);
  const [edit, setEdit] = useState<Vendor | "new" | null>(null);
  const [q, setQ] = useState("");
  const shown = (vendors.data ?? []).filter((v) => !q || [v.name_en, v.name_ar, v.vat, v.iban].some((x) => x?.toLowerCase().includes(q.toLowerCase())));

  async function remove(v: Vendor) {
    if (!confirm(t("Delete {name}? Invoices already decided keep their decision.", { name: v.name_en || v.name_ar || "" }))) return;
    try { await api(`/vendors/${v.id}`, { method: "DELETE" }); toast(t("Vendor deleted")); vendors.reload(); pos.reload(); }
    catch (e) { toast((e as Error).message, "err"); }
  }
  async function removePo(p: PurchaseOrder) {
    if (!confirm(t("Delete PO {n}?", { n: p.po_number }))) return;
    try { await api(`/purchase-orders/${p.id}`, { method: "DELETE" }); pos.reload(); } catch (e) { toast((e as Error).message, "err"); }
  }

  return (
    <>
      <Head title={t("Vendors")} sub={t("The vendor master: who you buy from, their VAT number and the bank account you pay. Invoices are matched to it by name or VAT number.")}>
        {admin && <button className="btn primary" onClick={() => setEdit("new")}>{t("Add vendor")}</button>}
      </Head>
      {!admin && <div className="notice warn" style={{ marginBottom: 14 }}>{t("Only admins can change vendors and purchase orders.")}</div>}
      <div className="row wrap" style={{ marginBottom: 12 }}>
        <input type="search" placeholder={t("Search vendors")} aria-label={t("Search vendors")} value={q} onChange={(e) => setQ(e.target.value)} />
        {admin && <CsvImport path="/vendors/import" label={t("Import vendors from CSV")} onDone={vendors.reload} />}
      </div>
      {admin && <p className="muted small" style={{ marginTop: -4 }}>{t("CSV columns:")} <bdi dir="ltr">name_en, name_ar, vat_number, iban, currency, status</bdi></p>}
      <Err msg={vendors.error} />
      <div className="panel flush">
        {vendors.data && !shown.length ? <Empty title={q ? t("Nothing matches the search.") : t("No vendors yet")} /> : (
          <div className="tw"><table>
            <thead><tr><th>{t("Name")}</th><th>{t("VAT number")}</th><th>{t("IBAN")}</th><th>{t("Currency")}</th><th>{t("Status")}</th><th>{t("Linked names")}</th>{admin && <th><span className="sr-only">{t("Actions")}</span></th>}</tr></thead>
            <tbody>{shown.map((v) => (
              <tr key={v.id}>
                <td><div className="cell-text" dir="auto">{v.name_en}</div>{v.name_ar && <div className="cell-text small muted" dir="rtl" lang="ar">{v.name_ar}</div>}</td>
                <td className="num"><bdi dir="ltr">{v.vat || "–"}</bdi></td>
                <td className="num small"><bdi dir="ltr">{ibanText(v.iban)}</bdi></td>
                <td><bdi dir="ltr">{v.currency}</bdi></td>
                <td><span className={`pill ${v.status === "blocked" ? "s-rejected" : "s-approved"}`}>{t(STATUS[v.status])}</span></td>
                <td className="num">{v.linked_names}</td>
                {admin && <td className="row" style={{ gap: 6, justifyContent: "flex-end" }}>
                  <button className="btn small" onClick={() => setEdit(v)} aria-label={t("Edit {name}", { name: v.name_en || v.name_ar || "" })}>{t("Edit")}</button>
                  <button className="btn small danger" onClick={() => remove(v)} aria-label={t("Delete {name}", { name: v.name_en || v.name_ar || "" })}>{t("Delete")}</button>
                </td>}
              </tr>
            ))}</tbody>
          </table></div>
        )}
      </div>

      <h2 style={{ marginTop: 28 }}>{t("Purchase orders")}</h2>
      <p className="muted small">{t("An invoice that gives a PO number is compared with that PO: its vendor, currency and amount. The tolerance is set on the rule.")}</p>
      {admin && <div className="row wrap" style={{ marginBottom: 12 }}>
        <CsvImport path="/purchase-orders/import" label={t("Import purchase orders from CSV")} onDone={pos.reload} />
        <span className="muted small">{t("CSV columns:")} <bdi dir="ltr">po_number, vendor, amount, currency, status</bdi></span>
      </div>}
      <Err msg={pos.error} />
      <div className="panel flush">
        {pos.data && !pos.data.length ? <Empty title={t("No purchase orders yet")} /> : (
          <div className="tw"><table>
            <thead><tr><th>{t("PO number")}</th><th>{t("Vendor")}</th><th className="n">{t("Amount")}</th><th>{t("Status")}</th>{admin && <th><span className="sr-only">{t("Actions")}</span></th>}</tr></thead>
            <tbody>{pos.data?.map((p) => (
              <tr key={p.id}>
                <td><bdi dir="ltr">{p.po_number}</bdi></td>
                <td><span className="cell-text" dir="auto">{p.vendor_name || "–"}</span>{!p.vendor_id && p.vendor_name && <span className="small muted"> · {t("not in the vendor master")}</span>}</td>
                <td className="n"><bdi dir="ltr">{money(p.amount, p.currency)}</bdi></td>
                <td>{t(PO_STATUS[p.status])}</td>
                {admin && <td style={{ textAlign: "end" }}><button className="btn small danger" onClick={() => removePo(p)} aria-label={t("Delete PO {n}", { n: p.po_number })}>{t("Delete")}</button></td>}
              </tr>
            ))}</tbody>
          </table></div>
        )}
      </div>
      {edit && <VendorForm vendor={edit === "new" ? null : edit} onClose={() => setEdit(null)} onSaved={vendors.reload} />}
    </>
  );
}
