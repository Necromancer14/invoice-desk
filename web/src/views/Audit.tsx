import { useState } from "react";
import { api } from "../api";
import type { AuditRow } from "../types";
import { Empty, Err, Head, useApp, useLoad, when } from "../common";

export default function Audit() {
  const { t } = useApp();
  const [action, setAction] = useState("");
  const { data, error } = useLoad(() => api<AuditRow[]>(`/audit?limit=300${action ? `&action=${action}` : ""}`), [action]);
  const groups = [["", "Everything"], ["run", "Invoices"], ["review", "Reviews"], ["rule", "Rule changes"], ["settings", "Settings"], ["demo", "Resets"]];
  return (
    <>
      <Head title={t("Audit log")} sub="Who did what and when. Automatic decisions are logged as system, so every outcome can be explained later." />
      <div className="seg" role="group" aria-label="Filter" style={{ marginBottom: 14 }}>
        {groups.map(([v, l]) => <button key={v} aria-pressed={action === v} onClick={() => setAction(v)}>{l}</button>)}
      </div>
      <Err msg={error} />
      <div className="panel flush">
        {data && !data.length ? <Empty title="No entries" /> : (
          <div className="tw"><table><thead><tr><th>When</th><th>Who</th><th>Action</th><th>Target</th><th>Detail</th></tr></thead>
            <tbody>{data?.map((a) => <tr key={a.id}><td className="small muted" style={{ whiteSpace: "nowrap" }}>{when(a.ts)}</td><td>{a.actor}</td><td>{a.action}</td><td>{a.target}</td><td className="small">{a.detail}</td></tr>)}</tbody></table></div>
        )}
      </div>
    </>
  );
}
