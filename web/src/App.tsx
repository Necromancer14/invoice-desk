import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, demoLogin, passwordLogin, session, setUnauthorizedHandler } from "./api";
import { AppCtx, Err, makeT, setFormatLang, tk } from "./common";
import type { Role, Stats } from "./types";
import type { Lang } from "./i18n";
import Dashboard from "./views/Dashboard";
import Intake from "./views/Intake";
import Runs from "./views/Runs";
import Review from "./views/Review";
import Rules from "./views/Rules";
import Evaluation from "./views/Evaluation";
import Audit from "./views/Audit";
import Vendors from "./views/Vendors";
import Settings from "./views/Settings";

const TABS: { id: string; label: string; icon: string }[] = [
  { id: "dashboard", label: tk("Dashboard"), icon: "M3 13h5V3H3zM10 21h5V8h-5zM17 21h5V12h-5z" },
  { id: "intake", label: tk("Upload invoices"), icon: "M12 16V4m0 0l-4 4m4-4l4 4M4 20h16" },
  { id: "runs", label: tk("Runs"), icon: "M4 6h16M4 12h16M4 18h10" },
  { id: "review", label: tk("Review queue"), icon: "M5 12l4 4 10-10" },
  { id: "rules", label: tk("Rules"), icon: "M4 7h10M18 7h2M4 17h2M10 17h10M14 4v6M8 14v6" },
  { id: "vendors", label: tk("Vendors"), icon: "M3 21h18M5 21V8l7-4 7 4v13M9 21v-6h6v6M9 11h.01M15 11h.01" },
  { id: "evaluation", label: tk("Evaluation"), icon: "M4 20V10m6 10V4m6 16v-7m4 7H2" },
  { id: "audit", label: tk("Audit log"), icon: "M7 3h8l4 4v14H7zM15 3v4h4M10 12h6M10 16h6" },
  { id: "settings", label: tk("Settings"), icon: "M12 15a3 3 0 100-6 3 3 0 000 6zM19 12a7 7 0 00-.1-1.2l2-1.5-2-3.4-2.3.9a7 7 0 00-2-1.2L14 3h-4l-.6 2.6a7 7 0 00-2 1.2l-2.3-.9-2 3.4 2 1.5a7 7 0 000 2.4l-2 1.5 2 3.4 2.3-.9a7 7 0 002 1.2L10 21h4l.6-2.6a7 7 0 002-1.2l2.3.9 2-3.4-2-1.5c.1-.4.1-.8.1-1.2z" },
];

const ROLE_LABEL: Record<Role, string> = { admin: tk("Admin"), reviewer: tk("Reviewer"), viewer: tk("Viewer") };

const LogoMark = () => (
  <svg width="30" height="30" viewBox="0 0 32 32" aria-hidden="true"><defs><linearGradient id="lg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#19ac60" /><stop offset="1" stopColor="#006c35" /></linearGradient></defs><rect width="32" height="32" rx="10" fill="url(#lg)" /><path d="M9 7.5h10l4.5 4.5v12.5H9z" fill="none" stroke="#fff" strokeWidth="2" strokeLinejoin="round" /><path d="M13 17.5l3 3 5-6" fill="none" stroke="#fff" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" /></svg>
);

function parseHash(): { tab: string; arg?: string } {
  const [tab, arg] = location.hash.replace(/^#\/?/, "").split("/");
  return { tab: TABS.some((t) => t.id === tab) ? tab : "dashboard", arg };
}

type T = (s: string, vars?: Record<string, string | number>) => string;

/** How long to keep asking a sleeping server before giving up, and when to start saying so. */
const WAKE_GIVE_UP_MS = 90_000;
const WAKE_SAY_SO_MS = 3_000;

/**
 * Ask /api/health until it answers. A free Render instance sleeps when idle and takes about a minute to start; while it
 * starts, requests hang or come back 502/503. Only the API part of that is visible here: on a fully cold start the
 * browser also waits for this page itself, before any of this code runs.
 */
function useHealth(attempt: number) {
  const [health, setHealth] = useState<{ demo: boolean } | null>(null);
  const [state, setState] = useState<"checking" | "waking" | "failed">("checking");
  const [waited, setWaited] = useState(0);
  useEffect(() => {
    let stop = false;
    const started = Date.now();
    setState("checking"); setWaited(0);
    const tick = window.setInterval(() => {
      const ms = Date.now() - started;
      setWaited(Math.round(ms / 1000));
      if (ms >= WAKE_SAY_SO_MS) setState((s) => (s === "checking" ? "waking" : s));
    }, 1000);
    (async () => {
      while (!stop) {
        const ctrl = new AbortController();
        const cut = window.setTimeout(() => ctrl.abort(), 15_000);
        try {
          const r = await fetch("/api/health", { signal: ctrl.signal, cache: "no-store" });
          if (r.ok) { const h = await r.json(); if (!stop) { setHealth({ demo: !!h.demo }); } return; }
        } catch { /* asleep, starting or offline: ask again */ } finally { window.clearTimeout(cut); }
        if (Date.now() - started >= WAKE_GIVE_UP_MS) { if (!stop) setState("failed"); return; }
        await new Promise((res) => setTimeout(res, 3000));
      }
    })().finally(() => window.clearInterval(tick));
    return () => { stop = true; window.clearInterval(tick); };
  }, [attempt]);
  return { health, state, waited };
}

function Waking({ t, lang, setLang, failed, waited, retry }: { t: T; lang: Lang; setLang: (l: Lang) => void; failed: boolean; waited: number; retry: () => void }) {
  return (
    <main className="login"><div className="panel" role={failed ? "alert" : "status"} aria-live="polite">
      <div className="row" style={{ gap: 12 }}><svg width="40" height="40" viewBox="0 0 32 32" aria-hidden="true"><rect width="32" height="32" rx="8" fill="#006c35" /><path d="M9 7.5h10l4.5 4.5v12.5H9z" fill="none" stroke="#fff" strokeWidth="2" strokeLinejoin="round" /><path d="M13 17.5l3 3 5-6" fill="none" stroke="#fff" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" /></svg><div className="grow"><h1>invoice-desk</h1></div>
        <button className="chip" style={{ alignSelf: "start" }} onClick={() => setLang(lang === "en" ? "ar" : "en")} aria-label={t("Switch language")}>{lang === "en" ? "العربية" : "English"}</button></div>
      {failed ? <>
        <h2>{t("The demo did not wake up")}</h2>
        <p className="muted">{t("The server has not answered for 90 seconds. It may be down, or your connection may be offline.")}</p>
        <div><button className="btn primary" onClick={retry}>{t("Try again")}</button></div>
      </> : <>
        <div className="row" style={{ gap: 14 }}><span className="spinner" aria-hidden="true" /><h2>{t("Waking up the demo")}</h2></div>
        <p className="muted">{t("This free demo server sleeps when nobody is using it, and starting it again can take about a minute. The page will carry on by itself.")}</p>
        <p className="muted small num">{t("Waiting for {n} seconds", { n: waited })}</p>
      </>}
    </div></main>
  );
}

function Login({ onIn, t, lang, setLang, demo }: { onIn: (r: Role, name: string) => void; t: T; lang: Lang; setLang: (l: Lang) => void; demo: boolean }) {
  const [err, setErr] = useState<string | null>(null);
  const [name, setName] = useState(""); const [pw, setPw] = useState("");
  async function pick(role: Role) {
    try { const r = await demoLogin(role); session.token = r.token; onIn(r.role, r.name); } catch (e) { setErr(t((e as Error).message)); }
  }
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    try { const r = await passwordLogin(name, pw); session.token = r.token; onIn(r.role, r.name); } catch (x) { setErr(t((x as Error).message)); }
  }
  return (
    <main className="login"><div className="panel">
      <div className="row" style={{ gap: 12 }}><svg width="40" height="40" viewBox="0 0 32 32" aria-hidden="true"><rect width="32" height="32" rx="8" fill="#006c35" /><path d="M9 7.5h10l4.5 4.5v12.5H9z" fill="none" stroke="#fff" strokeWidth="2" strokeLinejoin="round" /><path d="M13 17.5l3 3 5-6" fill="none" stroke="#fff" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" /></svg><div className="grow"><h1>invoice-desk</h1><p className="muted">{t("Saudi e-invoice intake with human review")}</p></div>
        <button className="chip" style={{ alignSelf: "start" }} onClick={() => setLang(lang === "en" ? "ar" : "en")} aria-label={t("Switch language")}>{lang === "en" ? "العربية" : "English"}</button></div>
      <Err msg={err} />
      {demo && <div className="roles" role="group" aria-label={t("Sign in as")}>
        <p className="muted small">{t("This is a demo with made-up data. Pick a role to look around.")}</p>
        <button onClick={() => pick("admin")}><b>{t("Admin")}</b><span className="muted small">{t("Everything, including editing rules and settings")}</span></button>
        <button onClick={() => pick("reviewer")}><b>{t("Reviewer")}</b><span className="muted small">{t("Upload invoices and decide the ones waiting for review")}</span></button>
        <button onClick={() => pick("viewer")}><b>{t("Viewer")}</b><span className="muted small">{t("Read-only")}</span></button>
      </div>}
      {!demo && <form className="col" onSubmit={submit}>
        <label className="f">{t("Name")}<input type="text" value={name} onChange={(e) => setName(e.target.value)} autoComplete="username" /></label>
        <label className="f">{t("Password")}<input type="password" value={pw} onChange={(e) => setPw(e.target.value)} autoComplete="current-password" /></label>
        <button className="btn primary" type="submit">{t("Sign in")}</button></form>}
    </div></main>
  );
}

export default function App() {
  const [role, setRole] = useState<Role | null>(null);
  const [name, setName] = useState("");
  const [theme, setThemeState] = useState(document.documentElement.dataset.theme || "light");
  const [lang, setLangState] = useState<Lang>((document.documentElement.lang as Lang) || "en");
  const [route, setRoute] = useState(parseHash());
  const [open, setOpen] = useState(false);
  const [queue, setQueue] = useState(0);
  const [toastMsg, setToastMsg] = useState<{ msg: string; kind: "ok" | "err" } | null>(null);
  const [checked, setChecked] = useState(false);

  const setTheme = (t: string) => { document.documentElement.dataset.theme = t; setThemeState(t); try { localStorage.setItem("id-theme", t); } catch { /* blocked */ } };
  const setLang = (l: Lang) => {
    document.documentElement.lang = l; document.documentElement.dir = l === "ar" ? "rtl" : "ltr"; setLangState(l);
    try { localStorage.setItem("id-lang", l); } catch { /* blocked */ }
  };
  const logout = useCallback(() => { session.token = null; setRole(null); }, []);
  useEffect(() => { setUnauthorizedHandler(logout); }, [logout]);
  const [wakeAttempt, setWakeAttempt] = useState(0);
  const { health, state: wake, waited } = useHealth(wakeAttempt);
  useEffect(() => {
    if (!health) return;
    if (!session.token) { setChecked(true); return; }
    api<{ name: string; role: Role }>("/auth/me").then((m) => { setRole(m.role); setName(m.name); }).catch(() => {}).finally(() => setChecked(true));
  }, [health]);
  useEffect(() => { const h = () => { setRoute(parseHash()); setOpen(false); }; window.addEventListener("hashchange", h); return () => window.removeEventListener("hashchange", h); }, []);

  // The review badge. A decision lowers it at once (change = -1) and the server's count follows. Only the newest
  // answer counts, so a slow reply from before the decision cannot put the old number back. While invoices are
  // still being processed the count is fetched again every 1.5 s instead of waiting for the 8 s heartbeat.
  const countSeq = useRef(0);
  const countPoll = useRef<number | undefined>(undefined);
  const refreshCounts = useCallback((change = 0) => {
    const seq = ++countSeq.current;
    if (change) setQueue((q) => Math.max(0, q + change));
    api<Stats>("/stats").then((s) => {
      if (seq !== countSeq.current) return;
      setQueue(s.review_queue);
      window.clearTimeout(countPoll.current);
      if (s.by_status.queued + s.by_status.processing > 0) countPoll.current = window.setTimeout(() => refreshCounts(), 1500);
    }).catch(() => {});
  }, []);
  const setQueueCount = useCallback((n: number) => { countSeq.current++; setQueue(n); }, []);
  useEffect(() => { if (role) { refreshCounts(); const id = setInterval(() => refreshCounts(), 8000); return () => { clearInterval(id); window.clearTimeout(countPoll.current); }; } }, [role, refreshCounts]);
  useEffect(() => { if (!toastMsg) return; const id = setTimeout(() => setToastMsg(null), 4000); return () => clearTimeout(id); }, [toastMsg]);

  const go = useCallback((tab: string, arg?: string) => { location.hash = `#/${tab}${arg ? "/" + arg : ""}`; }, []);
  const t = useMemo(() => { setFormatLang(lang); return makeT(lang); }, [lang]);
  const ctx = useMemo(() => ({ t, lang, role: role ?? "viewer", name, toast: (msg: string, kind: "ok" | "err" = "ok") => setToastMsg({ msg, kind }), refreshCounts, setQueueCount, go }), [t, lang, role, name, refreshCounts, setQueueCount, go]);

  if (!health) return wake === "checking" ? null : <Waking t={t} lang={lang} setLang={setLang} failed={wake === "failed"} waited={waited} retry={() => setWakeAttempt((a) => a + 1)} />;
  if (!checked) return null;
  if (!role) return <Login t={t} lang={lang} setLang={setLang} demo={health.demo} onIn={(r, n) => { setRole(r); setName(n); }} />;

  const view = (() => {
    switch (route.tab) {
      case "intake": return <Intake />;
      case "runs": return <Runs openId={route.arg ? Number(route.arg) : undefined} />;
      case "review": return <Review openId={route.arg ? Number(route.arg) : undefined} />;
      case "rules": return <Rules />;
      case "vendors": return <Vendors />;
      case "evaluation": return <Evaluation />;
      case "audit": return <Audit />;
      case "settings": return <Settings theme={theme} setTheme={setTheme} lang={lang} setLang={setLang} />;
      default: return <Dashboard />;
    }
  })();

  return (
    <AppCtx.Provider value={ctx}>
      <div className="topbar"><button aria-label={t("Open menu")} onClick={() => setOpen(true)}>☰</button>invoice-desk</div>
      <div className="shell">
        <aside className={`side ${open ? "open" : ""}`} aria-label={t("Main")}>
          <div className="brand"><LogoMark />invoice-desk</div>
          <nav className="nav">
            {TABS.map((tab) => (
              <button key={tab.id} aria-current={route.tab === tab.id ? "page" : undefined} onClick={() => go(tab.id)}>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={tab.icon} /></svg>
                {t(tab.label)}{tab.id === "review" && queue > 0 && <span className="count" aria-label={t("{n} waiting", { n: queue })}>{queue}</span>}
              </button>
            ))}
          </nav>
          <div className="side-foot">
            <div className="who">{name} · {t(ROLE_LABEL[role])}</div>
            <div className="row">
              <button className="chip" onClick={() => setTheme(theme === "dark" ? "light" : "dark")} aria-label={t("Switch theme")}>{theme === "dark" ? `☀ ${t("Light")}` : `☾ ${t("Dark")}`}</button>
              <button className="chip" onClick={() => setLang(lang === "en" ? "ar" : "en")} aria-label={t("Switch language")}>{lang === "en" ? "العربية" : "English"}</button>
              <button className="chip" onClick={logout}>{t("Sign out")}</button>
            </div>
          </div>
        </aside>
        <main className="main" id="main">
          {health.demo && <p className="demo-note" role="note">{t("Demo with sample data. Resets on restart. Do not upload real invoices.")}</p>}
          {view}
        </main>
      </div>
      {toastMsg && <div className={`toast notice ${toastMsg.kind === "err" ? "err" : "ok"}`} role="status">{t(toastMsg.msg)}</div>}
    </AppCtx.Provider>
  );
}
