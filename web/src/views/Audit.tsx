import { useState } from "react";
import { api } from "../api";
import type { AuditRow } from "../types";
import { Empty, Err, Head, tk, useApp, useLoad, when } from "../common";

const GROUPS = [["", tk("Everything")], ["run", tk("Invoices")], ["review", tk("Reviews")], ["rule", tk("Rule changes")], ["settings", tk("Settings")], ["demo", tk("Resets")]];

export default function Audit() {
  const { t } = useApp();
  const [action, setAction] = useState("");
  const { data, error } = useLoad(() => api<AuditRow[]>(`/audit?limit=300${action ? `&action=${action}` : ""}`), [action]);
  return (
    <>
      <Head title={t("Audit log")} sub={t("Who did what and when. Automatic decisions are logged as system, so every outcome can be explained later.")} />
      <div className="seg" role="group" aria-label={t("Filter")} style={{ marginBottom: 14 }}>
        {GROUPS.map(([v, l]) => <button key={v} aria-pressed={action === v} onClick={() => setAction(v)}>{t(l)}</button>)}
      </div>
      <Err msg={error} />
      <div className="panel flush">
        {data && !data.length ? <Empty title={t("No entries")} /> : (
          <div className="tw"><table><thead><tr><th>{t("When")}</th><th>{t("Who")}</th><th>{t("Action")}</th><th>{t("Target")}</th><th>{t("Detail")}</th></tr></thead>
            {/* actor, action code, target id and detail are recorded data, shown as written and kept left-to-right */}
            <tbody>{data?.map((a) => <tr key={a.id}><td className="small muted" style={{ whiteSpace: "nowrap" }}>{when(a.ts)}</td><td><bdi dir="ltr">{a.actor === "system" ? t("system") : a.actor}</bdi></td><td><bdi dir="ltr">{a.action}</bdi></td><td><bdi dir="ltr">{a.target}</bdi></td><td className="small"><bdi dir="ltr">{a.detail}</bdi></td></tr>)}</tbody></table></div>
        )}
      </div>
    </>
  );
}
