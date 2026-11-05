import { useCallback, useEffect, useMemo, useState } from "react";
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
import Settings from "./views/Settings";

const TABS: { id: string; label: string; icon: string }[] = [
  { id: "dashboard", label: tk("Dashboard"), icon: "M3 13h5V3H3zM10 21h5V8h-5zM17 21h5V12h-5z" },
  { id: "intake", label: tk("Upload invoices"), icon: "M12 16V4m0 0l-4 4m4-4l4 4M4 20h16" },
  { id: "runs", label: tk("Runs"), icon: "M4 6h16M4 12h16M4 18h10" },
  { id: "review", label: tk("Review queue"), icon: "M5 12l4 4 10-10" },
  { id: "rules", label: tk("Rules"), icon: "M4 7h10M18 7h2M4 17h2M10 17h10M14 4v6M8 14v6" },
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

function Login({ onIn, t, lang, setLang }: { onIn: (r: Role, name: string) => void; t: (s: string) => string; lang: Lang; setLang: (l: Lang) => void }) {
  const [demo, setDemo] = useState<boolean | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [name, setName] = useState(""); const [pw, setPw] = useState("");
  useEffect(() => { fetch("/api/health").then((r) => r.json()).then((h) => setDemo(!!h.demo)).catch(() => setErr(t("Cannot reach the server."))); }, []);
  async function pick(role: Role) {
    try { const r = await demoLogin(role); session.token = r.token; onIn(r.role, r.name); } catch (e) { setErr((e as Error).message); }
  }
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    try { const r = await passwordLogin(name, pw); session.token = r.token; onIn(r.role, r.name); } catch (x) { setErr((x as Error).message); }
  }
  return (
    <div className="login"><div className="panel">
      <div className="row" style={{ gap: 12 }}><svg width="40" height="40" viewBox="0 0 32 32" aria-hidden="true"><rect width="32" height="32" rx="8" fill="#006c35" /><path d="M9 7.5h10l4.5 4.5v12.5H9z" fill="none" stroke="#fff" strokeWidth="2" strokeLinejoin="round" /><path d="M13 17.5l3 3 5-6" fill="none" stroke="#fff" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" /></svg><div className="grow"><h1>invoice-desk</h1><p className="muted">{t("Saudi e-invoice intake with human review")}</p></div>
        <button className="chip" style={{ alignSelf: "start" }} onClick={() => setLang(lang === "en" ? "ar" : "en")} aria-label={t("Switch language")}>{lang === "en" ? "العربية" : "English"}</button></div>
      <Err msg={err} />
      {demo && <div className="roles" role="group" aria-label={t("Sign in as")}>
        <p className="muted small">{t("This is a demo with made-up data. Pick a role to look around.")}</p>
        <button onClick={() => pick("admin")}><b>{t("Admin")}</b><span className="muted small">{t("Everything, including editing rules and settings")}</span></button>
        <button onClick={() => pick("reviewer")}><b>{t("Reviewer")}</b><span className="muted small">{t("Upload invoices and decide the ones waiting for review")}</span></button>
        <button onClick={() => pick("viewer")}><b>{t("Viewer")}</b><span className="muted small">{t("Read-only")}</span></button>
      </div>}
      {demo === false && <form className="col" onSubmit={submit}>
        <label className="f">{t("Name")}<input type="text" value={name} onChange={(e) => setName(e.target.value)} autoComplete="username" /></label>
        <label className="f">{t("Password")}<input type="password" value={pw} onChange={(e) => setPw(e.target.value)} autoComplete="current-password" /></label>
        <button className="btn primary" type="submit">{t("Sign in")}</button></form>}
    </div></div>
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
  useEffect(() => {
    if (!session.token) { setChecked(true); return; }
    api<{ name: string; role: Role }>("/auth/me").then((m) => { setRole(m.role); setName(m.name); }).catch(() => {}).finally(() => setChecked(true));
  }, []);
  useEffect(() => { const h = () => { setRoute(parseHash()); setOpen(false); }; window.addEventListener("hashchange", h); return () => window.removeEventListener("hashchange", h); }, []);

  const refreshCounts = useCallback(() => { api<Stats>("/stats").then((s) => setQueue(s.review_queue)).catch(() => {}); }, []);
  useEffect(() => { if (role) { refreshCounts(); const id = setInterval(refreshCounts, 8000); return () => clearInterval(id); } }, [role, refreshCounts]);
  useEffect(() => { if (!toastMsg) return; const id = setTimeout(() => setToastMsg(null), 4000); return () => clearTimeout(id); }, [toastMsg]);

  const go = useCallback((tab: string, arg?: string) => { location.hash = `#/${tab}${arg ? "/" + arg : ""}`; }, []);
  const t = useMemo(() => { setFormatLang(lang); return makeT(lang); }, [lang]);
  const ctx = useMemo(() => ({ t, lang, role: role ?? "viewer", name, toast: (msg: string, kind: "ok" | "err" = "ok") => setToastMsg({ msg, kind }), refreshCounts, go }), [t, lang, role, name, refreshCounts, go]);

  if (!checked) return null;
  if (!role) return <Login t={t} lang={lang} setLang={setLang} onIn={(r, n) => { setRole(r); setName(n); }} />;

  const view = (() => {
    switch (route.tab) {
      case "intake": return <Intake />;
      case "runs": return <Runs openId={route.arg ? Number(route.arg) : undefined} />;
      case "review": return <Review openId={route.arg ? Number(route.arg) : undefined} />;
      case "rules": return <Rules />;
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
        <main className="main" id="main">{view}</main>
      </div>
      {toastMsg && <div className={`toast notice ${toastMsg.kind === "err" ? "err" : "ok"}`} role="status">{toastMsg.msg}</div>}
    </AppCtx.Provider>
  );
}
