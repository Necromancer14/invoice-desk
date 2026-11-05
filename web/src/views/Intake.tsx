import { useRef, useState } from "react";
import { api, session } from "../api";
import type { Provider, Sample } from "../types";
import { Err, Head, can, useApp, useLoad } from "../common";

export default function Intake() {
  const { t, role, go, toast, refreshCounts } = useApp();
  const [mode, setMode] = useState<"rules" | "ai">("rules");
  const [files, setFiles] = useState<File[]>([]);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const { data: samples } = useLoad(() => api<Sample[]>("/samples"), []);
  const { data: providers } = useLoad(() => api<Provider[]>("/llm/providers"), []);
  const hasKey = session.aiReady();
  const providerName = providers?.find((p) => p.id === session.provider)?.label;
  const allowed = can(role, "reviewer");

  async function afterSubmit(n: number) {
    toast(`${n} invoice${n === 1 ? "" : "s"} received`); refreshCounts(); go("runs");
  }
  async function upload() {
    setBusy(true); setErr(null);
    try {
      const form = new FormData();
      files.forEach((f) => form.append("files", f));
      form.append("mode", mode);
      const r = await api<{ ids: number[] }>("/runs", { form, ai: mode === "ai" });
      await afterSubmit(r.ids.length);
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }
  async function loadSamples(names: string[]) {
    setBusy(true); setErr(null);
    try {
      const r = await api<{ ids: number[] }>("/samples/submit", { body: { files: names, mode }, ai: mode === "ai" });
      await afterSubmit(r.ids.length);
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }
  const toggle = (f: string) => { const n = new Set(picked); n.has(f) ? n.delete(f) : n.add(f); setPicked(n); };
  const fmtTag = (s: Sample) => `${s.format.toUpperCase()}${s.lang === "ar" ? " · Arabic" : s.lang === "bi" ? " · bilingual" : s.lang === "hard" ? " · unusual wording" : ""}`;

  return (
    <>
      <Head title={t("Upload invoices")} sub="Drop files in, pick how they get read, and watch them move through validation. Text, PDF and image files up to 5 MB." />
      {!allowed && <div className="notice warn" style={{ marginBottom: 14 }}>You are signed in as a viewer. Sign in as reviewer or admin to upload.</div>}
      <div className="panel" style={{ marginBottom: 16 }}>
        <div className="row wrap">
          <b>How should invoices be read?</b>
          <div className="seg" role="group" aria-label="Reading mode">
            <button aria-pressed={mode === "rules"} onClick={() => setMode("rules")}>Built-in rules (free)</button>
            <button aria-pressed={mode === "ai"} onClick={() => setMode("ai")}>AI model{providerName ? `: ${providerName}` : ""}</button>
          </div>
        </div>
        {mode === "ai" && !hasKey && <div className="notice warn" style={{ marginTop: 10 }}>Claude mode needs your Anthropic API key. <button className="btn small" onClick={() => go("settings")}>Add it in Settings</button></div>}
        {mode === "rules" && <p className="muted small" style={{ marginTop: 8 }}>Rule-based reading handles clean text and PDFs with a text layer. Images and unusual layouts go to the review queue. Switch to an AI model to read those.</p>}
      </div>
      <Err msg={err} />
      <div className="grid g2">
        <div className="panel">
          <h2>Your files</h2>
          <div className={`dropzone ${over ? "over" : ""}`} role="button" tabIndex={0} onClick={() => input.current?.click()}
            onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current?.click()}
            onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
            onDrop={(e) => { e.preventDefault(); setOver(false); setFiles([...files, ...Array.from(e.dataTransfer.files)].slice(0, 20)); }}>
            <b>Drop invoices here</b><p className="muted small">or press to choose files</p>
            <input ref={input} type="file" multiple hidden accept=".txt,.pdf,.png,.jpg,.jpeg,.webp,.gif" onChange={(e) => setFiles([...files, ...Array.from(e.target.files || [])].slice(0, 20))} />
          </div>
          {files.length > 0 && (
            <div className="col" style={{ marginTop: 12 }}>
              {files.map((f, i) => <div className="row small" key={i}><span className="grow ellip">{f.name}</span><span className="muted">{(f.size / 1024).toFixed(0)} KB</span><button className="btn ghost small" aria-label={`Remove ${f.name}`} onClick={() => setFiles(files.filter((_, j) => j !== i))}>✕</button></div>)}
              <button className="btn primary" disabled={busy || !allowed || (mode === "ai" && !hasKey)} onClick={upload}>{busy ? "Uploading…" : `Process ${files.length} file${files.length === 1 ? "" : "s"}`}</button>
            </div>
          )}
        </div>
        <div className="panel">
          <h2>Try a sample</h2>
          <p className="muted small" style={{ marginBottom: 8 }}>Made-up invoices with known problems, so you can see what each rule catches. Loading the same sample twice gets the second copy rejected as a duplicate, which is the duplicate rule doing its job. Use Reset demo data on the Runs page to start clean.</p>
          {!samples ? <p className="muted">Loading…</p> : (
            <>
              <div className="row wrap" style={{ marginBottom: 8 }}>
                <button className="btn small" disabled={busy || !allowed} onClick={() => loadSamples(samples.filter((s) => s.format === "txt").slice(0, 12).map((s) => s.file))}>Load 12 text samples</button>
                <button className="btn small" disabled={busy || !allowed} onClick={() => loadSamples(samples.map((s) => s.file))}>Load all {samples.length}</button>
                <button className="btn small primary right" disabled={busy || !allowed || !picked.size || (mode === "ai" && !hasKey)} onClick={() => loadSamples([...picked])}>Process {picked.size || ""} selected</button>
              </div>
              <div style={{ maxHeight: 420, overflowY: "auto" }}>
                {samples.map((s) => (
                  <label key={s.file} className="sample check">
                    <input type="checkbox" checked={picked.has(s.file)} onChange={() => toggle(s.file)} />
                    <span className="grow">{s.label}<span className="muted small"> · {s.file}</span></span>
                    <span className="tag">{fmtTag(s)}</span>
                  </label>
                ))}
              </div>
            </>
          )}
        </div>
      </div>
    </>
  );
}
