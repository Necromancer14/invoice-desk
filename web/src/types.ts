export type Role = "viewer" | "reviewer" | "admin";
export type Status = "queued" | "processing" | "approved" | "needs_review" | "rejected" | "approved_human" | "rejected_human" | "failed";
export type Severity = "reject" | "review" | "info";

export interface LineItem { description: string; quantity: number | null; unit_price: number | null; line_total: number | null }
export interface Fields {
  invoice_number: string | null; issue_date: string | null; due_date: string | null; seller_name: string | null; seller_vat: string | null;
  buyer_name: string | null; buyer_vat: string | null; currency: string | null; subtotal: number | null; vat_amount: number | null;
  total: number | null; qr_payload: string | null; line_items: LineItem[] | null;
}
export interface RuleResult { key: string; name: string; severity: Severity; status: "pass" | "fail" | "skip"; detail: string }
export interface TraceStep { step: string; ms: number; ok: boolean; detail: string; at: string }
export interface RunSummary {
  id: number; filename: string; content_type: string; size: number; source: string; status: Status; mode: "rules" | "ai";
  created_at: string; updated_at: string; decided_at: string | null; decision_by: string | null; submitted_by: string; edited: boolean;
  error: string | null; confidence: number | null; extractor: string | null; fields: Fields | null;
  summary?: { invoice_number: string | null; seller_name: string | null; total: number | null; currency: string | null };
}
export interface Extraction {
  confidence: number; field_confidence: Record<string, number>; notes: string[]; extractor: string; model: string | null;
  tokens_in: number; tokens_out: number; latency_ms: number;
}
export interface RunDetail extends RunSummary {
  extracted: Fields | null; final_fields: Fields | null; extraction: Extraction; results: RuleResult[]; trace: TraceStep[]; decision_note: string | null;
}
export interface Stats {
  total: number; by_status: Record<Status, number>; review_queue: number; auto_approve_rate: number | null; human_corrected: number;
  avg_extract_ms: number | null; avg_time_to_review_s: number | null; tokens_in: number; tokens_out: number; cost: number | null;
  ai_runs: number; top_failing: { rule: string; count: number }[]; series: { day: string; count: number }[]; rules_version: number;
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
  mode: string; count: number; as_of: string; ran_at?: string; field_accuracy: number; decision_agreement: number; auto_approve_rate: number;
  review_rate: number; unsafe_auto_approvals: number; false_rejections: number; tokens_in: number; tokens_out: number;
  by_field: Record<string, number>; by_format: Record<string, Slice>; by_lang: Record<string, Slice>; by_scenario: Record<string, Slice>; rows: EvalRow[];
}
export interface Settings { default_mode: "rules" | "ai"; price_in_per_mtok: string; price_out_per_mtok: string; auto_approve: "true" | "false" }
export interface Provider { id: string; label: string; free: boolean; model: string; images: boolean; key_url: string; note: string; needs_key: boolean }
