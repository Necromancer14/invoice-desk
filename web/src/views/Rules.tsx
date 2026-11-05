import { useState } from "react";
import { api } from "../api";
import type { ParamSpec, Rule, RuleTypes, RuleVersion, Severity, Simulation } from "../types";
import { Empty, Err, Head, Modal, can, useApp, useLoad, when } from "../common";

const SEV: Record<Severity, string> = { reject: "Rejects the invoice", review: "Sends it to review", info: "Informational only" };
const sevClass: Record<Severity, string> = { reject: "s-rejected", review: "s-needs_review", info: "s-queued" };

export default function Rules() {
  const { t, role, toast } = useApp();
  const admin = can(role, "admin");
  const rules = useLoad(() => api<{ rules: Rule[]; version: number }>("/rules"), []);
  const types = useLoad(() => api<RuleTypes>("/rules/types"), []);
  const versions = useLoad(() => api<RuleVersion[]>("/rules/versions"), []);
  const [edit, setEdit] = useState<Rule | "new" | null>(null);
  const refresh = () => { rules.reload(); versions.reload(); };

  async function toggle(r: Rule) {
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
    if (!confirm(`Restore the rules as they were in version ${v}? The current set stays in the history.`)) return;
    try { await api("/rules/rollback", { body: { version: v } }); toast(`Restored version ${v}`); refresh(); } catch (e) { toast((e as Error).message, "err"); }
  }

  return (
    <>
      <Head title={t("Rules")} sub="These rules decide whether an invoice is approved, sent to a person or rejected. Change them here and the next invoice follows the new rule. No deployment needed.">
        {admin && <button className="btn primary" onClick={() => setEdit("new")}>Add rule</button>}
      </Head>
      {!admin && <div className="notice warn" style={{ marginBottom: 14 }}>Only admins can change rules. You can read them and the history.</div>}
      <Err msg={rules.error || types.error} />
      <div className="grid g2">
        <div className="col">
          {rules.data?.rules.map((r, i) => (
            <div key={r.key} className={`rulecard ${r.enabled ? "" : "off"}`}>
              <div className="col" style={{ gap: 0 }}>
                <button className="btn ghost small" disabled={!admin || i === 0} aria-label={`Move ${r.name} up`} onClick={() => move(i, -1)}>▲</button>
                <button className="btn ghost small" disabled={!admin || i === rules.data!.rules.length - 1} aria-label={`Move ${r.name} down`} onClick={() => move(i, 1)}>▼</button>
              </div>
              <div style={{ minWidth: 0 }}>
                <b>{r.name}</b>
                <div className="row wrap small muted" style={{ gap: 8, marginTop: 3 }}>
                  <span className={`pill ${sevClass[r.severity]}`} style={{ padding: "0 8px" }}>{SEV[r.severity]}</span>
                  <span>{types.data?.types[r.type]?.label ?? r.type}</span>
                </div>
              </div>
              <div className="row">
                <label className="check small"><input type="checkbox" checked={r.enabled} disabled={!admin} onChange={() => toggle(r)} /> On</label>
                <button className="btn small" onClick={() => setEdit(r)}>{admin ? "Edit" : "View"}</button>
              </div>
            </div>
          ))}
          {rules.data && !rules.data.rules.length && <Empty title="No rules" hint="With no rules every invoice is approved. Add one to get started." />}
        </div>
        <div className="panel" style={{ alignSelf: "start" }}>
          <h2>Version history</h2>
          <div className="col" style={{ gap: 0 }}>
            {versions.data?.map((v, i) => (
              <div key={v.version} className="row" style={{ padding: "8px 0", borderBottom: "1px solid var(--line)" }}>
                <div className="grow"><b>Version {v.version}</b>{i === 0 && <span className="tag" style={{ marginInlineStart: 8 }}>current</span>}<div className="small muted">{v.note} · {v.author} · {when(v.created_at)}</div></div>
                {admin && i > 0 && <button className="btn small" onClick={() => rollback(v.version)}>Restore</button>}
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
  const { toast } = useApp();
  const [r, setR] = useState<Rule>(rule ?? { key: "", name: "", type: "vat_rate", params: {}, severity: "review", enabled: true, message: "" });
  const [note, setNote] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [sim, setSim] = useState<Simulation | null>(null);
  const [busy, setBusy] = useState(false);
  const spec = types.types[r.type];
  const val = (p: ParamSpec) => (p.name in r.params ? r.params[p.name] : p.default);
  const setParam = (p: ParamSpec, v: unknown) => { setR({ ...r, params: { ...r.params, [p.name]: v } }); setSim(null); };
  const full = (): Rule => ({ ...r, params: Object.fromEntries(spec.params.map((p) => [p.name, val(p)])) });

  async function simulate() {
    setBusy(true); setErr(null);
    try { setSim(await api<Simulation>("/rules/simulate", { body: { rule: full() } })); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }
  async function save() {
    setBusy(true); setErr(null);
    try { await api("/rules", { body: { ...full(), note } }); toast("Rule saved. It applies to the next invoice."); onSaved(); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }
  async function remove() {
    if (!confirm(`Delete "${r.name}"?`)) return;
    try { await api(`/rules/${r.key}`, { method: "DELETE" }); toast("Rule deleted"); onSaved(); } catch (e) { setErr((e as Error).message); }
  }
  const dis = !admin;
  return (
    <Modal title={rule ? (admin ? "Edit rule" : "Rule") : "Add rule"} onClose={onClose}>
      <label className="f">Name<input type="text" value={r.name} disabled={dis} onChange={(e) => setR({ ...r, name: e.target.value })} placeholder="e.g. Flag invoices over 20,000" /></label>
      <div className="grid" style={{ gridTemplateColumns: "1fr 1fr" }}>
        <label className="f">What it checks
          <select value={r.type} disabled={dis || !!rule} onChange={(e) => { setR({ ...r, type: e.target.value, params: {} }); setSim(null); }}>
            {Object.entries(types.types).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
          </select>
        </label>
        <label className="f">If it fails
          <select value={r.severity} disabled={dis} onChange={(e) => { setR({ ...r, severity: e.target.value as Severity }); setSim(null); }}>
            {(Object.keys(SEV) as Severity[]).map((s) => <option key={s} value={s}>{SEV[s]}</option>)}
          </select>
        </label>
      </div>
      <p className="muted small">{spec.description}</p>
      {spec.params.map((p) => (
        <div key={p.name}>
          {p.kind === "bool" ? (
            <label className="check"><input type="checkbox" disabled={dis} checked={!!val(p)} onChange={(e) => setParam(p, e.target.checked)} />{p.name.replace(/_/g, " ")}</label>
          ) : (
            <label className="f">{p.name.replace(/_/g, " ")}{p.help && <span className="hint"> · {p.help}</span>}
              {p.kind === "field" ? <select disabled={dis} value={String(val(p))} onChange={(e) => setParam(p, e.target.value)}>{types.fields.map((f) => <option key={f}>{f}</option>)}</select>
                : p.kind === "number" ? <input type="number" step="any" disabled={dis} value={String(val(p))} onChange={(e) => setParam(p, e.target.value === "" ? "" : Number(e.target.value))} />
                : p.kind === "list" ? <input type="text" disabled={dis} value={(val(p) as string[]).join(", ")} onChange={(e) => setParam(p, e.target.value.split(",").map((s) => s.trim()).filter(Boolean))} />
                : r.type === "expression" ? <textarea disabled={dis} value={String(val(p))} onChange={(e) => setParam(p, e.target.value)} />
                : <input type="text" disabled={dis} value={String(val(p))} onChange={(e) => setParam(p, e.target.value)} />}
            </label>
          )}
          {r.type === "expression" && p.name === "expr" && (
            <p className="muted small" style={{ marginTop: 4 }}>Fields: {types.fields.filter((f) => f !== "line_items" && f !== "qr_payload").join(", ")}, item_count, today, confidence. Helpers: {types.functions.join(", ")}. Example: <code>total &lt;= 20000 or buyer_vat != None</code></p>
          )}
        </div>
      ))}
      <label className="f">Message shown to reviewers when it fails <span className="hint">(optional)</span><input type="text" disabled={dis} value={r.message} onChange={(e) => setR({ ...r, message: e.target.value })} /></label>
      {admin && <label className="f">Note for the version history <span className="hint">(optional)</span><input type="text" value={note} onChange={(e) => setNote(e.target.value)} /></label>}
      <Err msg={err} />
      {sim && (
        <div className={`notice ${sim.changed_count ? "warn" : "ok"}`}>
          {sim.changed_count === 0 ? `Checked against ${sim.checked} past invoices: no decision would change.` :
            <><b>{sim.changed_count} of {sim.checked} past invoices would get a different decision.</b>
              <ul style={{ margin: "6px 0 0", paddingInlineStart: 18 }}>{Object.entries(sim.shift).map(([k, n]) => <li key={k}>{n} × {k.replace(/_/g, " ")}</li>)}</ul></>}
        </div>
      )}
      {admin && (
        <div className="row wrap">
          <button className="btn" disabled={busy} onClick={simulate}>Check impact on past invoices</button>
          <button className="btn primary" disabled={busy || !r.name.trim()} onClick={save}>Save rule</button>
          {rule && <button className="btn danger right" onClick={remove}>Delete</button>}
        </div>
      )}
    </Modal>
  );
}
