"""Pick an AI model to read invoices. Free options first; nothing here stores keys."""
from __future__ import annotations

import base64
import os
import re
import time

import httpx

from .extractors import (IMAGE_TYPES, JSON_PROMPT, ClaudeExtractor, Extraction, NeedsVision, _overall, normalise,
                         parse_json_loose, pdf_text)

PROVIDERS: dict[str, dict] = {
    "gemini": dict(label="Google Gemini", kind="gemini", free=True, model="gemini-3.8-flash", images=True, pdf=True,
                   key_url="https://aistudio.google.com/apikey",
                   note="Free key from Google AI Studio, no card needed. Reads images and PDFs. Google may use free-tier content to improve its products, so only use made-up invoices."),
    "groq": dict(label="Groq", kind="openai", base="https://api.groq.com/openai/v1", free=True, model="llama-3.3-70b-versatile", images=False, pdf=False,
                 key_url="https://console.groq.com/keys",
                 note="Free plan with rate limits. Text and PDFs with a text layer only; images go to the review queue."),
    "openrouter": dict(label="OpenRouter", kind="openai", base="https://openrouter.ai/api/v1", free=True, model="meta-llama/llama-3.3-70b-instruct:free",
                       images=False, pdf=False, key_url="https://openrouter.ai/keys",
                       note="Has models whose id ends in :free. Free model names change, so check openrouter.ai/models and paste one. Text and text-layer PDFs only."),
    "ollama": dict(label="Ollama (on this computer)", kind="openai", base="http://localhost:11434/v1", free=True, model="llama3.2", images=False, pdf=False,
                   local=True, key_url="https://ollama.com/download",
                   note="Runs a model on your own machine, no key and no cost. Only works when you run invoice-desk locally with INVOICE_DESK_ALLOW_LOCAL=1."),
    "claude": dict(label="Anthropic Claude", kind="anthropic", free=False, model="claude-sonnet-5-5", images=True, pdf=True,
                   key_url="https://console.anthropic.com/settings/keys",
                   note="Paid API key from the Anthropic Console. A Claude Pro chat subscription does not include API credits."),
    "openai": dict(label="OpenAI", kind="openai", base="https://api.openai.com/v1", free=False, model="gpt-4o-mini", images=True, pdf=False,
                   key_url="https://platform.openai.com/api-keys", note="Paid API key. Reads images; PDFs are read as text or as page images."),
}


class ProviderError(Exception):
    pass


def public_providers() -> list[dict]:
    allow_local = os.environ.get("INVOICE_DESK_ALLOW_LOCAL") == "1"
    out = []
    for pid, p in PROVIDERS.items():
        if p.get("local") and not allow_local:
            continue
        out.append(dict(id=pid, label=p["label"], free=p["free"], model=p["model"], images=p["images"], key_url=p["key_url"],
                        note=p["note"], needs_key=not p.get("local")))
    return out


def _clean_error(resp: httpx.Response, label: str) -> str:
    try:
        j = resp.json()
        msg = (j.get("error") or {}).get("message") if isinstance(j.get("error"), dict) else j.get("error") or j.get("message")
    except Exception:
        msg = resp.text
    hint = {401: "the key was not accepted", 403: "the key is not allowed to use this model", 404: "that model name was not found",
            429: "rate limit or quota reached, wait a minute or use another provider"}.get(resp.status_code, "")
    return f"{label} returned {resp.status_code}" + (f" ({hint})" if hint else "") + (f": {str(msg)[:160]}" if msg else "")


def _pdf_pages_png(blob: bytes, limit: int = 3) -> list[bytes]:
    import io

    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(blob)
    out = []
    for i in range(min(len(pdf), limit)):
        buf = io.BytesIO()
        pdf[i].render(scale=1.6).to_pil().save(buf, "PNG")
        out.append(buf.getvalue())
    return out


GEMINI_MODEL_NOT_FOUND = "That model name isn't available. Type a current model name in the Model box (see aistudio.google.com)."


class GeminiExtractor:
    name = "gemini"

    def __init__(self, api_key: str, model: str, transport: httpx.BaseTransport | None = None):
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", model or ""):
            raise ProviderError("model name has characters that are not allowed")
        self.key, self.model = api_key, model
        self.http = httpx.Client(timeout=90, transport=transport)

    def extract(self, blob: bytes, content_type: str, filename: str = "") -> Extraction:
        t0 = time.time()
        if content_type in IMAGE_TYPES or content_type == "application/pdf":
            part = {"inline_data": {"mime_type": content_type, "data": base64.b64encode(blob).decode()}}
        else:
            part = {"text": "<invoice>\n" + blob.decode("utf-8", "replace") + "\n</invoice>"}
        body = {"systemInstruction": {"parts": [{"text": JSON_PROMPT}]},
                "contents": [{"role": "user", "parts": [part, {"text": "Extract this invoice and reply with the JSON object."}]}],
                "generationConfig": {"temperature": 0, "responseMimeType": "application/json"}}
        r = self.http.post(f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent",
                           headers={"x-goog-api-key": self.key}, json=body)
        if r.status_code == 404:
            # Google retires model names; say what to do rather than echo its long message.
            raise ProviderError(GEMINI_MODEL_NOT_FOUND)
        if r.status_code >= 400:
            raise ProviderError(_clean_error(r, "Gemini"))
        j = r.json()
        try:
            text = "".join(p.get("text", "") for p in j["candidates"][0]["content"]["parts"])
        except (KeyError, IndexError, TypeError):
            raise ProviderError("Gemini returned no answer (the document may have been blocked)") from None
        fields, fc, notes = normalise(parse_json_loose(text))
        u = j.get("usageMetadata") or {}
        return Extraction(fields, _overall(fields, fc), fc, notes, "gemini", self.model, u.get("promptTokenCount", 0) or 0,
                          u.get("candidatesTokenCount", 0) or 0, int((time.time() - t0) * 1000))


class OpenAICompatExtractor:
    """Groq, OpenRouter, OpenAI and Ollama all speak this chat-completions format."""

    def __init__(self, provider: str, api_key: str | None, model: str, transport: httpx.BaseTransport | None = None):
        p = PROVIDERS[provider]
        if not re.fullmatch(r"[A-Za-z0-9._:/-]{1,100}", model or ""):
            raise ProviderError("model name has characters that are not allowed")
        self.name, self.label, self.base, self.key, self.model = provider, p["label"], p["base"], api_key, model
        self.vision = p["images"] or (provider == "ollama" and any(w in model.lower() for w in ("vision", "llava", "gemma3", "qwen2.5vl")))
        self.http = httpx.Client(timeout=120, transport=transport)

    def _user_content(self, blob: bytes, ct: str):
        if ct in IMAGE_TYPES:
            if not self.vision:
                raise NeedsVision(f"{self.label} with this model cannot read images")
            return [self._img(blob, ct)]
        if ct == "application/pdf":
            text = pdf_text(blob)
            if len(text.strip()) >= 20:
                return "<invoice>\n" + text + "\n</invoice>"
            if not self.vision:
                raise NeedsVision("PDF has no text layer and this model cannot read images")
            return [self._img(b, "image/png") for b in _pdf_pages_png(blob)]
        return "<invoice>\n" + blob.decode("utf-8", "replace") + "\n</invoice>"

    @staticmethod
    def _img(b: bytes, ct: str) -> dict:
        return {"type": "image_url", "image_url": {"url": f"data:{ct};base64,{base64.b64encode(b).decode()}"}}

    def extract(self, blob: bytes, content_type: str, filename: str = "") -> Extraction:
        t0 = time.time()
        content = self._user_content(blob, content_type)
        if isinstance(content, list):
            content = content + [{"type": "text", "text": "Extract this invoice and reply with the JSON object."}]
        else:
            content += "\n\nExtract this invoice and reply with the JSON object."
        body = {"model": self.model, "temperature": 0, "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": JSON_PROMPT}, {"role": "user", "content": content}]}
        headers = {"Authorization": f"Bearer {self.key}"} if self.key else {}
        r = self.http.post(f"{self.base}/chat/completions", headers=headers, json=body)
        if r.status_code == 400 and "response_format" in r.text.lower():  # some hosts do not support JSON mode
            body.pop("response_format")
            r = self.http.post(f"{self.base}/chat/completions", headers=headers, json=body)
        if r.status_code >= 400:
            raise ProviderError(_clean_error(r, self.label))
        j = r.json()
        try:
            text = j["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise ProviderError(f"{self.label} returned no answer") from None
        fields, fc, notes = normalise(parse_json_loose(text))
        u = j.get("usage") or {}
        return Extraction(fields, _overall(fields, fc), fc, notes, self.name, self.model, u.get("prompt_tokens", 0) or 0,
                          u.get("completion_tokens", 0) or 0, int((time.time() - t0) * 1000))


def build_extractor(llm: dict, transport: httpx.BaseTransport | None = None):
    """llm = {provider, key, model?}. Raises ProviderError with a message a person can act on."""
    pid = (llm or {}).get("provider") or ""
    p = PROVIDERS.get(pid)
    if not p or (p.get("local") and os.environ.get("INVOICE_DESK_ALLOW_LOCAL") != "1"):
        raise ProviderError("choose an AI provider in Settings")
    key = (llm.get("key") or "").strip()
    if not key and not p.get("local"):
        raise ProviderError(f"{p['label']} needs an API key (add it in Settings)")
    model = (llm.get("model") or "").strip() or p["model"]
    if p["kind"] == "anthropic":
        return ClaudeExtractor(api_key=key, model=model)
    if p["kind"] == "gemini":
        return GeminiExtractor(key, model, transport)
    return OpenAICompatExtractor(pid, key or None, model, transport)
