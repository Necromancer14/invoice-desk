import { useMemo, useState } from "react";
import { api, download } from "../api";
import type { RunDetail, RunSummary, Status } from "../types";
import { Empty, Err, Head, Modal, SourceFilter, type Source, StatusPill, can, money, tk, useApp, useLoad, when } from "../common";
import { LOCALE } from "../i18n";
import { Document, Evidence, RunHeader } from "./RunDetail";

const FILTERS: { label: string; value: string }[] = [
  { label: tk("All"), value: "" }, { label: tk("Needs review"), value: "needs_review" }, { label: tk("Approved"), value: "approved,approved_human" },
  { label: tk("Rejected"), value: "rejected,rejected_human" }, { label: tk("Failed"), value: "failed" },
];

type SortKey = "id" | "file" | "number" | "seller" | "total" | "status" | "created";
/** Status order when sorting: what needs attention first. */
const STATUS_ORDER: Status[] = ["needs_review", "failed", "rejected", "rejected_human", "approved", "approved_human", "processing", "queued"];
const sortValue = (r: RunSummary, k: SortKey): string | number | null => {
  switch (k) {
    case "id": case "created": return r.id;
    case "file": return r.filename;
    case "number": return r.summary?.invoice_number ?? null;
    case "seller": return r.summary?.seller_name ?? null;
    case "total": return r.summary?.total ?? null;
    case "status": return STATUS_ORDER.indexOf(r.status as Status);
  }
};

const Caret = ({ dir }: { dir?: "ascending" | "descending" }) => (
  <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true" className={`caret${dir ? " on" : ""}`}>
    <path d="M2 4l3-3 3 3" fill="none" stroke="currentColor" strokeWidth="1.5" opacity={dir === "descending" ? 0.35 : 1} />
    <path d="M2 6l3 3 3-3" fill="none" stroke="currentColor" strokeWidth="1.5" opacity={dir === "ascending" ? 0.35 : 1} />
  </svg>
);

export default function Runs({ openId }: { openId?: number }) {
  const { t, toast, lang } = useApp();
  const [sort, setSort] = useState<{ k: SortKey; asc: boolean }>({ k: "id", asc: false });
  const [status, setStatus] = useState("");
  const [source, setSource] = useState<Source>("upload");
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<number | null>(openId ?? null);
  const { data, error, reload } = useLoad(
    () => api<{ total: number; items: RunSummary[] }>(`/runs?limit=100&source=${source}${status ? `&status=${status}` : ""}${q ? `&q=${encodeURIComponent(q)}` : ""}`),
    [status, q, source], (d) => d.items.some((r) => r.status === "queued" || r.status === "processing"));
  // Sorting reorders the rows already loaded (the newest 100 for this filter); it does not ask the server again.
  const rows = useMemo(() => {
    if (!data) return [];
    const coll = new Intl.Collator(LOCALE[lang], { numeric: true, sensitivity: "base" });
    return [...data.items].sort((a, b) => {
      const x = sortValue(a, sort.k), y = sortValue(b, sort.k);
      if (x == null || y == null) return x == null ? (y == null ? 0 : 1) : -1;  // blanks last either way
      const c = typeof x === "number" && typeof y === "number" ? x - y : coll.compare(String(x), String(y));
      return sort.asc ? c : -c;
    });
  }, [data, sort, lang]);
  const th = (k: SortKey, label: string, n?: boolean) => {
    const dir = sort.k === k ? (sort.asc ? "ascending" : "descending") : undefined;
    // text columns start A to Z; numbers and dates start with the largest or newest
    const first = k === "file" || k === "number" || k === "seller" || k === "status";
    return (
      <th className={n ? "n" : undefined} aria-sort={dir}>
        <button className="th-sort" onClick={() => setSort((s) => ({ k, asc: s.k === k ? !s.asc : first }))}>{label}<Caret dir={dir} /></button>
      </th>
    );
  };
  return (
    <>
      <Head title={t("Runs")} sub={t("Every invoice the system has handled, newest first. Open one to see what was read, which checks it passed and who decided.")}>
        <button className="btn" onClick={() => download("/export.csv", "approved-invoices.csv").catch((e) => toast(e.message, "err"))}>{t("Export approved (CSV)")}</button>
      </Head>
      <div className="toolbar">
        <div className="seg" role="group" aria-label={t("Filter by status")}>
          {FILTERS.map((f) => <button key={f.label} aria-pressed={status === f.value} onClick={() => setStatus(f.value)}>{t(f.label)}</button>)}
        </div>
        <SourceFilter value={source} onChange={setSource} />
        <input type="search" className="toolbar-search" placeholder={t("Search")} aria-label={t("Search runs")} value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      <Err msg={error} />
      <div className="panel flush">
        {data && data.items.length === 0 ? <Empty title={t("Nothing here")} hint={t("Upload invoices or change the filter.")} /> : (
          <div className="tw"><table>
            <thead><tr>{th("id", "#")}{th("file", t("File"))}{th("number", t("Invoice number"))}{th("seller", t("Seller"))}{th("total", t("Total"), true)}{th("status", t("Status"))}{th("created", t("Created"))}</tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="click" tabIndex={0} onClick={() => setOpen(r.id)} onKeyDown={(e) => e.key === "Enter" && setOpen(r.id)}>
                  <td className="num muted">{r.id}</td><td><span className="cell-text muted" dir="ltr">{r.filename}</span></td><td><bdi dir="ltr">{r.summary?.invoice_number ?? "–"}</bdi></td>
                  <td><span className="cell-text" dir="auto">{r.summary?.seller_name ?? "–"}</span></td><td className="n amt"><bdi dir="ltr">{money(r.summary?.total, r.summary?.currency)}</bdi></td>
                  <td><StatusPill status={r.status as Status} /></td><td className="small muted nowrap">{when(r.created_at)}</td>
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
    <Modal title={t("Invoice run #{id}", { id })} onClose={onClose} wide>
      <Err msg={error} />
      {run && (
        <>
          <RunHeader run={run} />
          {run.error && <div className="notice err" dir="auto">{t(run.error)}</div>}
          {run.decision_note && <div className="notice">{t("Note")}: {run.decision_note}</div>}
          <div className="split run-split">
            <div className="doc-pane"><Document run={run} /></div>
            <div className="col run-side">
              <Evidence run={run} />
              {can(role, "reviewer") && run.status !== "queued" && run.status !== "processing" && (
                <div><button className="btn small" onClick={async () => {
                  try { await api(`/runs/${id}/reprocess`, { method: "POST", ai: run.mode === "ai" }); toast(t("Processing again")); refreshCounts(); reload(); } catch (e) { toast((e as Error).message, "err"); }
                }}>{t("Run again with the current rules")}</button></div>
              )}
            </div>
          </div>
        </>
      )}
    </Modal>
  );
}
