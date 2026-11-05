import { useState } from "react";
import { api, download } from "../api";
import type { RunDetail, RunSummary, Status } from "../types";
import { Empty, Err, Head, Modal, StatusPill, can, money, tk, useApp, useLoad, when } from "../common";
import { Document, Evidence, RunHeader } from "./RunDetail";

const FILTERS: { label: string; value: string }[] = [
  { label: tk("All"), value: "" }, { label: tk("Needs review"), value: "needs_review" }, { label: tk("Approved"), value: "approved,approved_human" },
  { label: tk("Rejected"), value: "rejected,rejected_human" }, { label: tk("Failed"), value: "failed" },
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
      <Head title={t("Runs")} sub={t("Every invoice the system has handled, newest first. Open one to see what was read, which checks it passed and who decided.")}>
        <button className="btn" onClick={() => download("/export.csv", "approved-invoices.csv").catch((e) => toast(e.message, "err"))}>{t("Export approved (CSV)")}</button>
      </Head>
      <div className="row wrap" style={{ marginBottom: 14 }}>
        <div className="seg" role="group" aria-label={t("Filter by status")}>
          {FILTERS.map((f) => <button key={f.label} aria-pressed={status === f.value} onClick={() => setStatus(f.value)}>{t(f.label)}</button>)}
        </div>
        <input type="search" placeholder={t("Search")} aria-label={t("Search runs")} value={q} onChange={(e) => setQ(e.target.value)} style={{ maxWidth: 260 }} />
        {can(role, "admin") && <button className="btn small right" onClick={async () => { if (confirm(t("Clear all runs and audit entries and restore the default rules?"))) { await api("/admin/reset", { body: {} }); toast(t("Demo reset")); refreshCounts(); reload(); } }}>{t("Reset demo data")}</button>}
      </div>
      <Err msg={error} />
      <div className="panel flush">
        {data && data.items.length === 0 ? <Empty title={t("Nothing here")} hint={t("Upload invoices or change the filter.")} /> : (
          <div className="tw"><table>
            <thead><tr><th>#</th><th>{t("File")}</th><th>{t("Invoice number")}</th><th>{t("Seller")}</th><th className="n">{t("Total")}</th><th>{t("Status")}</th><th>{t("Created")}</th></tr></thead>
            <tbody>
              {data?.items.map((r) => (
                <tr key={r.id} className="click" tabIndex={0} onClick={() => setOpen(r.id)} onKeyDown={(e) => e.key === "Enter" && setOpen(r.id)}>
                  <td className="num">{r.id}</td><td className="ellip" dir="ltr">{r.filename}</td><td><bdi dir="ltr">{r.summary?.invoice_number ?? "–"}</bdi></td>
                  <td className="ellip" dir="auto">{r.summary?.seller_name ?? "–"}</td><td className="n"><bdi dir="ltr">{money(r.summary?.total, r.summary?.currency)}</bdi></td>
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
  const { t, role, toast, refreshCounts } = useApp();
  const { data: run, error, reload } = useLoad(() => api<RunDetail>(`/runs/${id}`), [id], (d) => d.status === "queued" || d.status === "processing");
  return (
    <Modal title={t("Invoice run #{id}", { id })} onClose={onClose}>
      <Err msg={error} />
      {run && (
        <>
          <RunHeader run={run} />
          {run.error && <div className="notice err">{run.error}</div>}
          {run.decision_note && <div className="notice">{t("Note")}: {run.decision_note}</div>}
          <Document run={run} />
          <Evidence run={run} />
          {can(role, "reviewer") && run.status !== "queued" && run.status !== "processing" && (
            <div><button className="btn small" onClick={async () => {
              try { await api(`/runs/${id}/reprocess`, { method: "POST", ai: run.mode === "ai" }); toast(t("Processing again")); refreshCounts(); reload(); } catch (e) { toast((e as Error).message, "err"); }
            }}>{t("Run again with the current rules")}</button></div>
          )}
        </>
      )}
    </Modal>
  );
}
