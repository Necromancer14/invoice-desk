import { useState } from "react";
import { api, download } from "../api";
import type { RunDetail, RunSummary, Status } from "../types";
import { Empty, Err, Head, Modal, StatusPill, can, money, useApp, useLoad, when } from "../common";
import { Document, Evidence, RunHeader } from "./RunDetail";

const FILTERS: { label: string; value: string }[] = [
  { label: "All", value: "" }, { label: "Needs review", value: "needs_review" }, { label: "Approved", value: "approved,approved_human" },
  { label: "Rejected", value: "rejected,rejected_human" }, { label: "Failed", value: "failed" },
];

export default function Runs({ openId }: { openId?: number }) {
  const { t, role, toast, refreshCounts } = useApp();
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<number | null>(openId ?? null);
  const { data, error, reload } = useLoad(
    () => api<{ total: number; items: RunSummary[] }>(`/runs?limit=100${status ? `&status=${status}` : ""}${q ? `&q=${encodeURIComponent(q)}` : ""}`),
    [status, q], (d) => d.items.some((r) => r.status === "queued" || r.status === "processing"));
  return (
    <>
      <Head title={t("Runs")} sub="Every invoice the system has handled, newest first. Open one to see what was read, which checks it passed and who decided.">
        <button className="btn" onClick={() => download("/export.csv", "approved-invoices.csv").catch((e) => toast(e.message, "err"))}>Export approved (CSV)</button>
      </Head>
      <div className="row wrap" style={{ marginBottom: 14 }}>
        <div className="seg" role="group" aria-label="Filter by status">
          {FILTERS.map((f) => <button key={f.label} aria-pressed={status === f.value} onClick={() => setStatus(f.value)}>{t(f.label)}</button>)}
        </div>
        <input type="search" placeholder={t("Search")} aria-label="Search runs" value={q} onChange={(e) => setQ(e.target.value)} style={{ maxWidth: 260 }} />
        {can(role, "admin") && <button className="btn small right" onClick={async () => { if (confirm("Clear all runs and audit entries and restore the default rules?")) { await api("/admin/reset", { body: {} }); toast("Demo reset"); refreshCounts(); reload(); } }}>Reset demo data</button>}
      </div>
      <Err msg={error} />
      <div className="panel flush">
        {data && data.items.length === 0 ? <Empty title="Nothing here" hint="Upload invoices or change the filter." /> : (
          <div className="tw"><table>
            <thead><tr><th>#</th><th>{t("File")}</th><th>{t("Invoice number")}</th><th>{t("Seller")}</th><th className="n">{t("Total")}</th><th>{t("Status")}</th><th>{t("Created")}</th></tr></thead>
            <tbody>
              {data?.items.map((r) => (
                <tr key={r.id} className="click" tabIndex={0} onClick={() => setOpen(r.id)} onKeyDown={(e) => e.key === "Enter" && setOpen(r.id)}>
                  <td className="num">{r.id}</td><td className="ellip">{r.filename}</td><td>{r.summary?.invoice_number ?? "–"}</td>
                  <td className="ellip">{r.summary?.seller_name ?? "–"}</td><td className="n">{money(r.summary?.total, r.summary?.currency)}</td>
                  <td><StatusPill status={r.status as Status} /></td><td className="small muted">{when(r.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table></div>
        )}
      </div>
      {open != null && <RunModal id={open} onClose={() => { setOpen(null); reload(); }} />}
    </>
  );
}

function RunModal({ id, onClose }: { id: number; onClose: () => void }) {
  const { role, toast, refreshCounts } = useApp();
  const { data: run, error, reload } = useLoad(() => api<RunDetail>(`/runs/${id}`), [id], (d) => d.status === "queued" || d.status === "processing");
  return (
    <Modal title={`Invoice run #${id}`} onClose={onClose}>
      <Err msg={error} />
      {run && (
        <>
          <RunHeader run={run} />
          {run.error && <div className="notice err">{run.error}</div>}
          {run.decision_note && <div className="notice">Note: {run.decision_note}</div>}
          <Document run={run} />
          <Evidence run={run} />
          {can(role, "reviewer") && run.status !== "queued" && run.status !== "processing" && (
            <div><button className="btn small" onClick={async () => {
              try { await api(`/runs/${id}/reprocess`, { method: "POST", ai: run.mode === "ai" }); toast("Processing again"); refreshCounts(); reload(); } catch (e) { toast((e as Error).message, "err"); }
            }}>Run again with the current rules</button></div>
          )}
        </>
      )}
    </Modal>
  );
}
