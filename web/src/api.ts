import type { Role } from "./types";

const TOKEN = "id-token";
const PROVIDER = "id-llm-provider";
const MODEL = "id-llm-model";
const keyName = (p: string) => `id-llm-key-${p}`;

/**
 * Browser storage with an in-memory fallback. When storage is blocked (private mode, disabled site data,
 * sandboxed frames) or a write fails, values still live in memory for the current page view.
 * Anything written during this page view is read back from memory, so a failed write never loses it.
 */
function store(area: () => Storage) {
  const memory = new Map<string, string>(); // "" marks a value removed during this page view
  return {
    get(k: string): string {
      const m = memory.get(k);
      if (m !== undefined) return m;
      try { return area().getItem(k) || ""; } catch { return ""; }
    },
    set(k: string, v: string): void {
      memory.set(k, v);
      try { v ? area().setItem(k, v) : area().removeItem(k); } catch { /* storage blocked: memory only */ }
    },
  };
}

const local = store(() => localStorage);
// API keys live in sessionStorage only: gone when the tab closes, sent only to this server as a request header.
const tab = store(() => sessionStorage);

export const session = {
  get token() { return local.get(TOKEN) || null; },
  set token(v: string | null) { local.set(TOKEN, v || ""); },
  get provider() { return local.get(PROVIDER); }, set provider(v: string) { local.set(PROVIDER, v); },
  get model() { return local.get(MODEL); }, set model(v: string) { local.set(MODEL, v); },
  key(provider: string) { return tab.get(keyName(provider)); },
  setKey(provider: string, v: string) { tab.set(keyName(provider), v); },
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
