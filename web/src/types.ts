export type Role = "viewer" | "reviewer" | "admin";
export type Status = "queued" | "processing" | "approved" | "needs_review" | "rejected" | "approved_human" | "rejected_human" | "failed";
export type Severity = "reject" | "review" | "info";

export interface LineItem { description: string; quantity: number | null; unit_price: number | null; line_total: number | null; vat_category?: "S" | "Z" | "E" | "O" }
export interface Fields {
  invoice_number: string | null; issue_date: string | null; due_date: string | null; seller_name: string | null; seller_vat: string | null;
  buyer_name: string | null; buyer_vat: string | null; currency: string | null; subtotal: number | null; vat_amount: number | null;
  total: number | null; qr_payload: string | null; line_items: LineItem[] | null; invoice_type?: "standard" | "simplified" | null;
  iban?: string | null; po_number?: string | null;
}
export interface RuleResult { key: string; name: string; severity: Severity; status: "pass" | "fail" | "skip"; detail: string; risk?: "high" }
export interface TraceStep { step: string; ms: number; ok: boolean; detail: string; at: string }
export interface RunSummary {
  id: number; filename: string; content_type: string; size: number; source: string; status: Status; mode: "rules" | "ai";
  created_at: string; updated_at: string; decided_at: string | null; decision_by: string | null; submitted_by: string; edited: boolean;
  error: string | null; confidence: number | null; extractor: string | null; fields: Fields | null;
  summary?: { invoice_number: string | null; seller_name: string | null; total: number | null; currency: string | null };
}
export interface QueueItem {
  id: number; filename: string; created_at: string; seller: string | null; invoice_number: string | null;
  total: number | null; currency: string | null; failed_checks: number; high_risk?: boolean;
}
export interface Vendor {
  id: number; name_en: string | null; name_ar: string | null; vat: string | null; iban: string | null; currency: string;
  status: "approved" | "blocked"; linked_names?: number;
}
export interface PurchaseOrder { id: number; po_number: string; vendor_id: number | null; vendor_name: string | null; amount: number; currency: string; status: "open" | "closed" }
export interface ImportResult { added: number; updated: number; error_count: number; errors: { row: number; message: string }[] }
export interface VendorMatch {
  vendor: Vendor | null; score: number; matched_on: "English name" | "Arabic name" | "linked name" | "VAT number" | null; why: string;
  suggestions: { id: number; name_en: string | null; name_ar: string | null; score: number }[];
}
export type PoStatus = "no_po" | "not_found" | "vendor_mismatch" | "currency_mismatch" | "closed" | "over" | "matched";
export interface PoMatch { status: PoStatus; detail: string; po_number?: string; po_amount?: number; po_currency?: string; amount?: number | null }
export interface Extraction {
  confidence: number; field_confidence: Record<string, number>; notes: string[]; extractor: string; model: string | null;
  tokens_in: number; tokens_out: number; latency_ms: number;
}
export interface RunDetail extends RunSummary {
  extracted: Fields | null; final_fields: Fields | null; extraction: Extraction; results: RuleResult[]; trace: TraceStep[]; decision_note: string | null;
  vendor_match?: VendorMatch | null; po_match?: PoMatch; timeline?: TimelineEvent[];
}
/** One step in what happened to an invoice, built by the server from the audit log and the run's own fields. */
export type TimelineEvent = { at: string } & (
  | { kind: "received"; actor: string; mode: "rules" | "ai" }
  | { kind: "read"; ok: boolean; reader: string | null; model: string | null; confidence: number | null; fell_back: boolean }
  | { kind: "checked"; rules_version: number | null; checks: number; failed: number | null }
  | { kind: "routed"; outcome: "approved" | "needs_review" | "rejected"; auto_approve_off: boolean }
  | { kind: "failed" }
  | { kind: "reprocess"; actor: string }
  | { kind: "vendor_link"; actor: string }
  | { kind: "reviewed"; actor: string; decision: "approve" | "reject"; note: string; edited: string[] }
  | { kind: "copilot"; actor: string; recommendation: Recommendation }
);
/** What the review copilot suggests. It never decides: a person approves or rejects. */
export type Recommendation = "approve" | "reject" | "hold";
/** A finding of the rule-based copilot (and the guard note in Gemini mode): a code the portal words, plus its values. */
export interface Finding { code: string; effect: "reject" | "hold" | "info"; runs?: number[]; [k: string]: unknown }
/** Where an item of the finding came from. Shown as a small label; tool names never appear in the text. */
export type Source = "invoice" | "checks" | "vendor" | "vendor_history" | "iban_history" | "purchase_order" | "similar_invoices" | "reread" | "rule_test";
/** One reason or context item: the rule-based copilot sends a code the portal words, Gemini sends its own English and Arabic text. */
export type Item = { source: Source; effect?: "reject" | "hold" | "info"; runs?: number[]; [k: string]: unknown } & ({ code: string } | { en: string; ar: string });
export interface CopilotStep {
  n: number; tool: string; args: Record<string, unknown>; ok: boolean; ms: number;
  result: { code: string; [k: string]: unknown };
}
export interface Proposal {
  id: number; run_id: number; mode: "rules" | "gemini"; model: string | null; recommendation: Recommendation;
  summary: { en: string; ar: string } | null; reasons: Item[]; context: Item[]; steps: CopilotStep[]; finished: boolean;
  tokens_in: number; tokens_out: number; requested_by: string; created_at: string;
}
export interface CopilotRow {
  id: string; file: string; scenario: string; outcome: "ok" | "error"; correct?: Recommendation; recommended?: Recommendation;
  agree?: boolean; unsafe?: boolean; deferred?: boolean; could_not_read?: boolean; steps?: number; tokens_in?: number; tokens_out?: number; error?: string;
}
export interface CopilotEval {
  mode: "rules" | "gemini"; count: number; errors: number; agreement: number | null; unsafe_approves: number; holds: number;
  /** Items it gave an answer on (the rest were deferred), how many it deferred, and that as a share of all items. */
  answered: number; deferred: number; deferral_rate: number | null;
  recommended: Record<Recommendation, number>; avg_steps: number | null; avg_tokens_in: number | null; avg_tokens_out: number | null;
  unfinished: number; by_scenario: Record<string, { n: number; deferred: number; agree: number; unsafe: number }>; rows: CopilotRow[];
  model?: string | null; provider?: string; review_items?: number; sample_size?: number; seed?: number; rpm?: number;
  ran_at?: string; rules_version?: number; stopped?: { reason: string; message: string } | null; step_limit?: number;
}
export interface Stats {
  total: number; by_status: Record<Status, number>; review_queue: number; auto_approve_rate: number | null; human_corrected: number;
  avg_extract_ms: number | null; avg_time_to_review_s: number | null; tokens_in: number; tokens_out: number; cost: number | null;
  ai_runs: number; top_failing: { rule: string; count: number }[]; series: { day: string; count: number }[]; rules_version: number;
  top_rejections: { reason: string; count: number }[]; source: "upload" | "evaluation" | "all"; uploads: number;
  period?: Period;
}
/** Figures for one window of days. Values are SAR only; invoices in other currencies are counted, not converted. */
export interface PeriodFigures {
  received: number; approved: number; approved_human: number; waiting: number; rejected: number;
  auto_approve_rate: number | null; avg_time_to_review_s: number | null;
  value: { approved: number; waiting: number; rejected: number }; other_currency: number;
}
export interface PeriodDay { day: string; auto: number; person: number; review: number; rejected: number; value: number }
export interface Period {
  days: number; start: string; end: string; current: PeriodFigures; previous: PeriodFigures; series: PeriodDay[];
  top_failing: { rule: string; count: number }[]; top_rejections: { reason: string; count: number }[];
  waiting: QueueItem[]; waiting_count: number; waiting_value: number; high_risk: number;
  due_soon: { count: number; value: number; other_currency: number };
}
export interface Activity extends AuditRow {
  run: { seller_name: string | null; invoice_number: string | null; total: number | null; currency: string | null; filename: string } | null;
}
export interface Rule {
  key: string; name: string; type: string; params: Record<string, unknown>; severity: Severity; enabled: boolean; message: string;
}
export interface ParamSpec { name: string; kind: "field" | "number" | "bool" | "list" | "text"; default: unknown; help?: string }
export interface RuleType { label: string; description: string; params: ParamSpec[] }
export interface RuleTypes { types: Record<string, RuleType>; fields: string[]; functions: string[] }
export interface RuleVersion { version: number; author: string; note: string; created_at: string; rule_count: number }
export interface Simulation {
  checked: number; unchanged: number; changed_count: number; shift: Record<string, number>;
  changed: { id: number; filename: string; before: string; after: string }[];
}
export interface AuditRow { id: number; ts: string; actor: string; action: string; target: string; detail: string }
export interface Sample { id: string; file: string; format: string; lang: string; scenario: string; label: string; vision_only: boolean }
export interface EvalRow { id: string; file: string; format: string; lang: string; scenario: string; expected: string; got: string; agree: boolean; unsafe: boolean; false_reject: boolean; fields_ok: number; fields_total: number }
export interface Slice { n: number; agree: number; fields_ok: number; fields_total: number }
export interface EvalResult {
  mode?: string; count: number; errors?: number; fields_total?: number; as_of?: string; ran_at?: string; rules_version?: number;
  field_accuracy: number | null; decision_agreement: number | null; auto_approve_rate: number | null;
  review_rate: number | null; unsafe_auto_approvals: number; false_rejections: number; tokens_in?: number; tokens_out?: number;
  by_field: Record<string, number>; by_format: Record<string, Slice>; by_lang: Record<string, Slice>; by_scenario: Record<string, Slice>; rows: EvalRow[];
  copilot?: CopilotEval;
}
export interface EvalErrorRow { id: string; file: string; format: string; lang: string; scenario: string; outcome: "error"; error: string }
/** Everything evaluated so far with one AI model, combined across runs. */
export interface AiTotals extends EvalResult {
  provider: string; model: string; first_at: string; last_at: string; rules_versions: [number, number]; samples_total: number; error_rows: EvalErrorRow[];
}
export interface AiLastRun {
  provider: string; model: string; seed: number; sample_size: number; picked: number; attempted: number; evaluated: number; errors: number;
  stopped: { reason: "quota" | "rate_limit"; message: string } | null; rpm: number; only_new: boolean; skipped: number; ran_at: string; error_rows: EvalErrorRow[];
}
export interface Settings { default_mode: "rules" | "ai"; price_in_per_mtok: string; price_out_per_mtok: string; auto_approve: "true" | "false" }
export interface Provider { id: string; label: string; free: boolean; model: string; alt_models: string[]; images: boolean; key_url: string; note: string; needs_key: boolean }
