import { useState } from "react";
import { api } from "../api";
import type { ParamSpec, Rule, RuleTypes, RuleVersion, Severity, Simulation, Status } from "../types";
import { Empty, Err, FIELD_LABEL, Head, Modal, STATUS_LABEL, can, num, tk, useApp, useLoad, when } from "../common";

const SEV: Record<Severity, string> = { reject: tk("Rejects the invoice"), review: tk("Sends it to review"), info: tk("Informational only") };
const sevClass: Record<Severity, string> = { reject: "s-rejected", review: "s-needs_review", info: "s-queued" };
/** Parameter ids such as max_age_days, as a translatable label ("max age days"). */
const paramLabel = (name: string) => name.replace(/_/g, " ");

export default function Rules() {
  const { t, role, toast } = useApp();
  const admin = can(role, "admin");
  const rules = useLoad(() => api<{ rules: Rule[]; version: number }>("/rules"), []);
  const types = useLoad(() => api<RuleTypes>("/rules/types"), []);
  const versions = useLoad(() => api<RuleVersion[]>("/rules/versions"), []);
  const [edit, setEdit] = useState<Rule | "new" | null>(null);
  const refresh = () => { rules.reload(); versions.reload(); };

  async function toggle(r: Rule) {
    // The note goes into the version history, which is shared, so it stays in English like the other recorded data.
    try { await api("/rules", { body: { ...r, enabled: !r.enabled, note: `${r.enabled ? "Turned off" : "Turned on"} ${r.name}` } }); refresh(); }
    catch (e) { toast((e as Error).message, "err"); }
  }
  async function move(i: number, d: number) {
    const keys = rules.data!.rules.map((r) => r.key); const j = i + d;
    if (j < 0 || j >= keys.length) return;
    [keys[i], keys[j]] = [keys[j], keys[i]];
    try { await api("/rules/reorder", { method: "PUT", body: { keys } }); refresh(); } catch (e) { toast((e as Error).message, "err"); }
  }
  async function rollback(v: number) {
    if (!confirm(t("Restore the rules as they were in version {v}? The current set stays in the history.", { v }))) return;
    try { await api("/rules/rollback", { body: { version: v } }); toast(t("Restored version {v}", { v })); refresh(); } catch (e) { toast((e as Error).message, "err"); }
  }

  return (
    <>
      <Head title={t("Rules")} sub={t("These rules decide whether an invoice is approved, sent to a person or rejected. Change them here and the next invoice follows the new rule. No deployment needed.")}>
        {admin && <button className="btn primary" onClick={() => setEdit("new")}>{t("Add rule")}</button>}
      </Head>
      <p className="page-note">{t("These include checks against ZATCA e-invoicing fields: VAT number, VAT amounts, dates (Hijri too), the QR code and UBL XML. Signatures are not verified and nothing is sent to Fatoora.")} {t("The vendor rules compare the invoice with your vendor master and purchase orders; they skip while the vendor master is empty.")}</p>
      {!admin && <div className="notice warn mb">{t("Only admins can change rules. You can read them and the history.")}</div>}
      <Err msg={rules.error || types.error} />
      <div className="grid g2">
        <div className="panel flush rule-list">
          {rules.data?.rules.map((r, i) => (
            <div key={r.key} className={`rulecard ${r.enabled ? "" : "off"}`}>
              <div className="rule-move">
                <button className="btn ghost small" disabled={!admin || i === 0} aria-label={t("Move {name} up", { name: t(r.name) })} onClick={() => move(i, -1)}>▲</button>
                <button className="btn ghost small" disabled={!admin || i === rules.data!.rules.length - 1} aria-label={t("Move {name} down", { name: t(r.name) })} onClick={() => move(i, 1)}>▼</button>
              </div>
              <div className="rule-body">
                <b>{t(r.name)}</b>
                <div className="rule-meta">
                  <span className={`pill ${sevClass[r.severity]}`}>{t(SEV[r.severity])}</span>
                  <span>{t(types.data?.types[r.type]?.label ?? r.type)}</span>
                </div>
              </div>
              <div className="row">
                <label className="check small"><input type="checkbox" checked={r.enabled} disabled={!admin} onChange={() => toggle(r)} /> {t("On")}</label>
                <button className="btn small" onClick={() => setEdit(r)}>{admin ? t("Edit") : t("View")}</button>
              </div>
            </div>
          ))}
          {rules.data && !rules.data.rules.length && <Empty title={t("No rules")} hint={t("With no rules every invoice is approved. Add one to get started.")} />}
        </div>
        <div className="panel">
          <h2>{t("Version history")}</h2>
          <div className="vh">
            {versions.data?.map((v, i) => (
              <div key={v.version} className="vh-row">
                <div className="grow"><b>{t("Version {v}", { v: v.version })}</b>{i === 0 && <span className="tag vh-current">{t("current")}</span>}
                  {/* history notes and authors are recorded text, shown as written */}
                  <div className="small muted"><bdi>{v.note}</bdi> · <bdi dir="ltr">{v.author}</bdi> · {when(v.created_at)}</div></div>
                {admin && i > 0 && <button className="btn small" onClick={() => rollback(v.version)}>{t("Restore")}</button>}
              </div>
            ))}
          </div>
        </div>
      </div>
      {edit && types.data && <Editor types={types.data} rule={edit === "new" ? null : edit} admin={admin} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); refresh(); }} />}
    </>
  );
}

function Editor({ types, rule, admin, onClose, onSaved }: { types: RuleTypes; rule: Rule | null; admin: boolean; onClose: () => void; onSaved: () => void }) {
  const { t, toast } = useApp();
  const [r, setR] = useState<Rule>(rule ?? { key: "", name: "", type: "vat_rate", params: {}, severity: "review", enabled: true, message: "" });
  const [note, setNote] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [sim, setSim] = useState<Simulation | null>(null);
  const [busy, setBusy] = useState(false);
  const spec = types.types[r.type];
  const val = (p: ParamSpec) => (p.name in r.params ? r.params[p.name] : p.default);
  const setParam = (p: ParamSpec, v: unknown) => { setR({ ...r, params: { ...r.params, [p.name]: v } }); setSim(null); };
  const full = (): Rule => ({ ...r, params: Object.fromEntries(spec.params.map((p) => [p.name, val(p)])) });
  const fieldName = (f: string) => (FIELD_LABEL[f] ? t(FIELD_LABEL[f]) : f);
  /** "approved -> needs_review" from the simulation, in words; the arrow's direction comes from the translation. */
  const status = (s: string) => (s in STATUS_LABEL ? t(STATUS_LABEL[s as Status]) : s.replace(/_/g, " "));
  const shift = (k: string) => { const [from, to] = k.split(" -> "); return t("{from} → {to}", { from: status(from), to: status(to ?? "") }); };

  async function simulate() {
    setBusy(true); setErr(null);
    try { setSim(await api<Simulation>("/rules/simulate", { body: { rule: full() } })); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }
  async function save() {
    setBusy(true); setErr(null);
    try { await api("/rules", { body: { ...full(), note } }); toast(t("Rule saved. It applies to the next invoice.")); onSaved(); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }
  async function remove() {
    if (!confirm(t("Delete \"{name}\"?", { name: t(r.name) }))) return;
    try { await api(`/rules/${r.key}`, { method: "DELETE" }); toast(t("Rule deleted")); onSaved(); } catch (e) { setErr((e as Error).message); }
  }
  const dis = !admin;
  return (
    <Modal title={rule ? (admin ? t("Edit rule") : t("Rule")) : t("Add rule")} onClose={onClose}>
      <label className="f">{t("Name")}<input type="text" value={r.name} disabled={dis} onChange={(e) => setR({ ...r, name: e.target.value })} placeholder={t("e.g. Flag invoices over 20,000")} /></label>
      <div className="grid" style={{ gridTemplateColumns: "1fr 1fr" }}>
        <label className="f">{t("What it checks")}
          <select value={r.type} disabled={dis || !!rule} onChange={(e) => { setR({ ...r, type: e.target.value, params: {} }); setSim(null); }}>
            {Object.entries(types.types).map(([k, v]) => <option key={k} value={k}>{t(v.label)}</option>)}
          </select>
        </label>
        <label className="f">{t("If it fails")}
          <select value={r.severity} disabled={dis} onChange={(e) => { setR({ ...r, severity: e.target.value as Severity }); setSim(null); }}>
            {(Object.keys(SEV) as Severity[]).map((s) => <option key={s} value={s}>{t(SEV[s])}</option>)}
          </select>
        </label>
      </div>
      <p className="muted small">{t(spec.description)}</p>
      {spec.params.map((p) => (
        <div key={p.name}>
          {p.kind === "bool" ? (
            <label className="check"><input type="checkbox" disabled={dis} checked={!!val(p)} onChange={(e) => setParam(p, e.target.checked)} />{t(paramLabel(p.name))}</label>
          ) : (
            <label className="f">{t(paramLabel(p.name))}{p.help && <span className="hint"> · {t(p.help)}</span>}
              {p.kind === "field" ? <select disabled={dis} value={String(val(p))} onChange={(e) => setParam(p, e.target.value)}>{types.fields.map((f) => <option key={f} value={f}>{fieldName(f)}</option>)}</select>
                : p.kind === "number" ? <input type="number" dir="ltr" step="any" disabled={dis} value={val(p) == null ? "" : String(val(p))} onChange={(e) => setParam(p, e.target.value === "" ? null : Number(e.target.value))} />
                : p.kind === "list" ? <input type="text" dir="ltr" disabled={dis} value={(val(p) as string[]).join(", ")} onChange={(e) => setParam(p, e.target.value.split(",").map((s) => s.trim()).filter(Boolean))} />
                : r.type === "expression" ? <textarea dir="ltr" disabled={dis} value={String(val(p))} onChange={(e) => setParam(p, e.target.value)} />
                : <input type="text" dir="ltr" disabled={dis} value={String(val(p))} onChange={(e) => setParam(p, e.target.value)} />}
            </label>
          )}
          {r.type === "expression" && p.name === "expr" && (
            <p className="muted small" style={{ marginTop: 4 }}>
              {t("Fields")}: <bdi dir="ltr">{types.fields.filter((f) => f !== "line_items" && f !== "qr_payload").join(", ")}, item_count, today, confidence</bdi>.{" "}
              {t("Helpers")}: <bdi dir="ltr">{types.functions.join(", ")}</bdi>. {t("Example")}: <code dir="ltr">total &lt;= 20000 or buyer_vat != None</code>
            </p>
          )}
        </div>
      ))}
      <label className="f">{t("Message shown to reviewers when it fails")} <span className="hint">{t("(optional)")}</span><input type="text" disabled={dis} value={r.message} onChange={(e) => setR({ ...r, message: e.target.value })} /></label>
      {admin && <label className="f">{t("Note for the version history")} <span className="hint">{t("(optional)")}</span><input type="text" value={note} onChange={(e) => setNote(e.target.value)} /></label>}
      <Err msg={err} />
      {sim && (
        <div className={`notice ${sim.changed_count ? "warn" : "ok"}`}>
          {sim.changed_count === 0 ? t("Checked against {n} past invoices: no decision would change.", { n: sim.checked }) :
            <><b>{t("{changed} of {n} past invoices would get a different decision.", { changed: sim.changed_count, n: sim.checked })}</b>
              <ul style={{ margin: "6px 0 0", paddingInlineStart: 18 }}>{Object.entries(sim.shift).map(([k, n]) => <li key={k}>{num(n)} × {shift(k)}</li>)}</ul></>}
        </div>
      )}
      {admin && (
        <div className="row wrap">
          <button className="btn" disabled={busy} onClick={simulate}>{t("Check impact on past invoices")}</button>
          <button className="btn primary" disabled={busy || !r.name.trim()} onClick={save}>{t("Save rule")}</button>
          {rule && <button className="btn danger right" onClick={remove}>{t("Delete")}</button>}
        </div>
      )}
    </Modal>
  );
}
