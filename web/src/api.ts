import type { Role } from "./types";

const TOKEN = "id-token";
const PROVIDER = "id-llm-provider";
const MODEL = "id-llm-model";
const keyName = (p: string) => `id-llm-key-${p}`;

const ls = (k: string) => { try { return localStorage.getItem(k) || ""; } catch { return ""; } };
const lsSet = (k: string, v: string) => { try { v ? localStorage.setItem(k, v) : localStorage.removeItem(k); } catch { /* storage blocked */ } };

export const session = {
  get token() { try { return localStorage.getItem(TOKEN); } catch { return null; } },
  set token(v: string | null) { lsSet(TOKEN, v || ""); },
  get provider() { return ls(PROVIDER); }, set provider(v: string) { lsSet(PROVIDER, v); },
  get model() { return ls(MODEL); }, set model(v: string) { lsSet(MODEL, v); },
  // API keys live in sessionStorage only: gone when the tab closes, sent only to this server as a request header.
  key(provider: string) { try { return sessionStorage.getItem(keyName(provider)) || ""; } catch { return ""; } },
  setKey(provider: string, v: string) { try { v ? sessionStorage.setItem(keyName(provider), v) : sessionStorage.removeItem(keyName(provider)); } catch { /* storage blocked */ } },
  /** Ready to send AI requests: a provider is chosen and, unless it runs locally, a key is present. */
  aiReady(localProviders: string[] = ["ollama"]) { const p = this.provider; return !!p && (localProviders.includes(p) || !!this.key(p)); },
};

export function llmHeaders(): Record<string, string> {
  const p = session.provider;
  if (!p) return {};
  const h: Record<string, string> = { "X-LLM-Provider": p, "X-LLM-Key": session.key(p) };
  if (session.model) h["X-LLM-Model"] = session.model;
  return h;
}

let onUnauthorized: () => void = () => {};
export const setUnauthorizedHandler = (fn: () => void) => { onUnauthorized = fn; };

export class ApiError extends Error { constructor(message: string, public status: number) { super(message); } }

export async function api<T>(path: string, opts: { method?: string; body?: unknown; form?: FormData; ai?: boolean } = {}): Promise<T> {
  const headers: Record<string, string> = {};
  if (session.token) headers.Authorization = `Bearer ${session.token}`;
  if (opts.ai) Object.assign(headers, llmHeaders());
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) { headers["Content-Type"] = "application/json"; body = JSON.stringify(opts.body); }
  const res = await fetch(`/api${path}`, { method: opts.method || (body ? "POST" : "GET"), headers, body });
  if (res.status === 401) { onUnauthorized(); throw new ApiError("Your session ended. Pick a role to continue.", 401); }
  if (!res.ok) {
    let msg = res.statusText;
    try { const j = await res.json(); msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch { /* not json */ }
    throw new ApiError(msg, res.status);
  }
  const ct = res.headers.get("content-type") || "";
  return (ct.includes("json") ? res.json() : res.text()) as Promise<T>;
}

export async function fileBlobUrl(path: string): Promise<string> {
  const res = await fetch(`/api${path}`, { headers: session.token ? { Authorization: `Bearer ${session.token}` } : {} });
  if (!res.ok) throw new ApiError("Could not load the file", res.status);
  return URL.createObjectURL(await res.blob());
}

export async function download(path: string, name: string): Promise<void> {
  const url = await fileBlobUrl(path);
  const a = document.createElement("a");
  a.href = url; a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

export async function demoLogin(role: Role): Promise<{ token: string; role: Role; name: string }> {
  const res = await fetch("/api/auth/demo", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ role }) });
  if (!res.ok) throw new ApiError((await res.json().catch(() => ({}))).detail || "Demo sign in is switched off", res.status);
  return res.json();
}

export async function passwordLogin(name: string, password: string) {
  const res = await fetch("/api/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name, password }) });
  if (!res.ok) throw new ApiError((await res.json().catch(() => ({}))).detail || "Sign in failed", res.status);
  return res.json() as Promise<{ token: string; role: Role; name: string }>;
}
