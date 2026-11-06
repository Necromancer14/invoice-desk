import { useEffect, useState } from "react";
import { api, session } from "../api";
import type { Provider, Settings as S } from "../types";
import { Err, Head, can, useApp, useLoad } from "../common";

export default function Settings({ theme, setTheme, lang, setLang }: { theme: string; setTheme: (t: string) => void; lang: string; setLang: (l: "en" | "ar") => void }) {
  const { t, role, toast } = useApp();
  const { data, error, reload } = useLoad(() => api<S>("/settings"), []);
  const { data: providers } = useLoad(() => api<Provider[]>("/llm/providers"), []);
  const [form, setForm] = useState<S | null>(null);
  const [provider, setProvider] = useState(session.provider);
  const [model, setModel] = useState(session.model);
  const [key, setKey] = useState(provider ? session.key(provider) : "");
  const [err, setErr] = useState<string | null>(null);
  const [testing, setTesting] = useState(false);
  const [testMsg, setTestMsg] = useState<{ ok: boolean; text: string } | null>(null);
  useEffect(() => { if (data) setForm(data); }, [data]);
  const admin = can(role, "admin");
  const cur = providers?.find((p) => p.id === provider);

  function choose(p: Provider) {
    setProvider(p.id); setModel(""); setKey(session.key(p.id)); setTestMsg(null);
    session.provider = p.id; session.model = "";
  }
  function saveAi() {
    session.provider = provider; session.model = model.trim(); session.setKey(provider, key.trim());
    toast(provider ? t("Saved for this browser tab") : t("Nothing chosen"));
  }
  async function test() {
    saveAi(); setTesting(true); setTestMsg(null);
    try { const r = await api<{ ok: boolean; message: string; latency_ms: number }>("/llm/test", { method: "POST", ai: true }); setTestMsg({ ok: r.ok, text: `${t(r.message)} (${t("{ms} ms", { ms: r.latency_ms })})` }); }
    catch (e) { setTestMsg({ ok: false, text: t((e as Error).message) }); } finally { setTesting(false); }
  }
  async function save() {
    setErr(null);
    try { await api("/settings", { method: "PUT", body: form }); toast(t("Settings saved")); reload(); } catch (e) { setErr((e as Error).message); }
  }
  return (
    <>
      <Head title={t("Settings")} />
      <Err msg={error || err} />
      <div className="grid g2">
        <div className="col" style={{ gap: 18 }}>
          <div className="panel col">
            <h2>{t("AI model for reading invoices")}</h2>
            <p className="muted small">{t("Optional. The built-in reader is free and needs nothing. Pick a model if you want images, scans and unusual layouts read. Your key stays in this browser tab, is sent only to this server for the request, and is never saved or logged. Closing the tab forgets it.")}</p>
            <div className="providers" role="group" aria-label={t("AI provider")}>
              {providers?.map((p) => (
                <button key={p.id} className="provider" aria-pressed={provider === p.id} onClick={() => choose(p)}>
                  <span className="row wrap"><b>{t(p.label)}</b>{p.free ? <span className="tag free">{t("Free")}</span> : <span className="tag">{t("Paid")}</span>}{p.images && <span className="tag">{t("Reads images")}</span>}</span>
                  <span className="muted small">{t(p.note)}</span>
                </button>
              ))}
            </div>
            {cur && (
              <>
                {cur.needs_key && (
                  <label className="f">{t("API key")}
                    <input type="password" autoComplete="off" value={key} placeholder={t("paste your key")} onChange={(e) => setKey(e.target.value)} />
                    <span className="hint">{t("Get one at")} <a href={cur.key_url} target="_blank" rel="noreferrer"><bdi dir="ltr">{cur.key_url.replace("https://", "")}</bdi></a></span>
                  </label>
                )}
                <label className="f">{t("Model")} <span className="hint">{t("(leave empty for {model})", { model: cur.model })}</span>
                  <input type="text" dir="ltr" value={model} placeholder={cur.model} onChange={(e) => setModel(e.target.value)} />
                  {cur.alt_models.length > 0 && <span className="hint">{t("Also worth trying: {models}.", { models: cur.alt_models.join(", ") })}</span>}
                  <span className="hint">{t("Providers rename and retire models, and a name that works for one key may not work for a new one. If the test says a model isn't available, type a current name from the provider's site.")}</span>
                </label>
                <div className="row wrap">
                  <button className="btn primary" onClick={test} disabled={testing}>{testing ? t("Testing…") : t("Save and test connection")}</button>
                  <button className="btn" onClick={saveAi}>{t("Save only")}</button>
                  <button className="btn ghost" onClick={() => { session.setKey(provider, ""); setKey(""); setProvider(""); session.provider = ""; setTestMsg(null); }}>{t("Forget")}</button>
                </div>
                {testMsg && <div className={`notice ${testMsg.ok ? "ok" : "err"}`} role="status">{testMsg.text}</div>}
              </>
            )}
          </div>
          <div className="panel col">
            <h2>{t("Processing")}</h2>
            {!admin && <p className="muted small">{t("Only admins can change these.")}</p>}
            {form && <>
              <label className="f">{t("Default reading mode")}<select disabled={!admin} value={form.default_mode} onChange={(e) => setForm({ ...form, default_mode: e.target.value as S["default_mode"] })}><option value="rules">{t("Built-in rules")}</option><option value="ai">{t("AI model")}</option></select></label>
              <label className="check"><input type="checkbox" disabled={!admin} checked={form.auto_approve === "true"} onChange={(e) => setForm({ ...form, auto_approve: e.target.checked ? "true" : "false" })} />{t("Approve clean invoices automatically (turn off to send everything to review)")}</label>
              <div className="grid" style={{ gridTemplateColumns: "1fr 1fr" }}>
                <label className="f">{t("Input price per million tokens (USD)")}<input type="text" disabled={!admin} value={form.price_in_per_mtok} onChange={(e) => setForm({ ...form, price_in_per_mtok: e.target.value })} placeholder={t("from your provider")} /></label>
                <label className="f">{t("Output price per million tokens (USD)")}<input type="text" disabled={!admin} value={form.price_out_per_mtok} onChange={(e) => setForm({ ...form, price_out_per_mtok: e.target.value })} /></label>
              </div>
              <div><button className="btn primary" disabled={!admin} onClick={save}>{t("Save settings")}</button></div>
            </>}
          </div>
        </div>
        <div className="panel col" style={{ alignSelf: "start" }}>
          <h2>{t("Appearance")}</h2>
          <div className="row wrap"><span>{t("Theme")}</span><div className="seg"><button aria-pressed={theme === "light"} onClick={() => setTheme("light")}>{t("Light")}</button><button aria-pressed={theme === "dark"} onClick={() => setTheme("dark")}>{t("Dark")}</button></div></div>
          <div className="row wrap"><span>{t("Language")}</span><div className="seg"><button aria-pressed={lang === "en"} onClick={() => setLang("en")}>English</button><button aria-pressed={lang === "ar"} onClick={() => setLang("ar")}>العربية</button></div></div>
          <p className="muted small">{t("Arabic switches the layout to right-to-left and translates the whole portal. Invoice contents, rule names you type and server error messages are shown as written.")}</p>
        </div>
      </div>
    </>
  );
}
