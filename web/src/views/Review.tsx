import { api } from "../api";
import type { RunDetail } from "../types";
import { Empty, Err, Head, useApp, useLoad } from "../common";
import { Document, Evidence, ReviewForm, RunHeader } from "./RunDetail";

export default function Review() {
  const { t, go } = useApp();
  const { data, error, reload, loading } = useLoad(async () => {
    const r = await api<RunDetail | Record<string, never>>("/review/next");
    return ("id" in r ? r : null) as RunDetail | null;
  }, []);
  return (
    <>
      <Head title={t("Review queue")} sub="Invoices the rules could not settle on their own. Check the original on the left, fix anything the reader got wrong, then decide.">
        <span className="muted small">Shortcuts: <kbd>a</kbd> approve · <kbd>r</kbd> jump to note</span>
      </Head>
      <Err msg={error} />
      {!loading && !data && !error && <div className="panel"><Empty title="The queue is clear" hint="Nothing is waiting for a person right now."><p style={{ marginTop: 12 }}><button className="btn" onClick={() => go("intake")}>Upload more invoices</button></p></Empty></div>}
      {data && (
        <div className="col" style={{ gap: 14 }}>
          <RunHeader run={data} />
          <div className="split">
            <Document run={data} />
            <div className="panel"><ReviewForm run={data} onDone={() => reload()} /></div>
          </div>
          <div className="panel"><h2>Why this needs a person</h2><Evidence run={data} /></div>
        </div>
      )}
    </>
  );
}
