"""Validation rules as data.

A rule is a row: type, parameters, severity, enabled. Admins change rules in the portal
and the next invoice uses them, with no code deployment. Every change is a new version.

Custom logic uses the `expression` rule type. Expressions are parsed with `ast` and run by a
small evaluator that only knows numbers, strings, comparisons, boolean logic, arithmetic and a
fixed list of helper functions. There is no eval, no attribute access and no imports.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Callable

from . import qr
from .schema import FIELDS, NUMERIC, SCALARS, missing
from .textnorm import parse_date, to_number, vat_key

SEVERITIES = ("reject", "review", "info")


@dataclass
class Ctx:
    today: date = field(default_factory=date.today)
    confidence: float = 1.0
    is_duplicate: Callable[[str, str], bool] = lambda vat, number: False


def _f(fields: dict, name: str):
    v = fields.get(name)
    return to_number(v) if name in NUMERIC else v


def _close(a: float, b: float, tol: float) -> bool:
    return abs(a - b) <= tol


# ---- rule implementations: (params, fields, ctx) -> (status, detail) ----------------------

def r_required_fields(p, f, ctx):
    gone = missing(f, p.get("fields", []))
    return ("fail", "missing: " + ", ".join(gone)) if gone else ("pass", "all present")


def r_regex(p, f, ctx):
    v = f.get(p["field"])
    if v in (None, ""):
        return "skip", f"{p['field']} is empty"
    ok = re.fullmatch(p["pattern"], str(v)) is not None
    return ("pass", "matches") if ok else ("fail", f"{p['field']} '{v}' does not match {p['pattern']}")


def r_vat_number(p, f, ctx):
    name = p.get("field", "seller_vat")
    v = f.get(name)
    if v is None or not str(v).strip():
        return ("pass", "not provided") if p.get("optional") else ("skip", f"{name} is empty")
    # printed VAT numbers can be grouped ("300 000 000 000 003") or in Arabic-Indic digits; the number is the same
    ok = re.fullmatch(r"3[0-9]{13}3", vat_key(v)) is not None
    return ("pass", "valid format") if ok else ("fail", f"{name} '{v}' must be 15 digits starting and ending with 3")


def r_vat_rate(p, f, ctx):
    sub, vat = _f(f, "subtotal"), _f(f, "vat_amount")
    if sub is None or vat is None:
        return "skip", "subtotal or VAT amount missing"
    rate, tol = float(p.get("rate", 0.15)), float(p.get("tolerance", 0.05))
    exp = sub * rate
    if _close(vat, exp, tol):
        return "pass", f"VAT {vat:.2f} is {rate * 100:g}% of {sub:.2f}"
    return "fail", f"VAT is {vat:.2f} but {rate * 100:g}% of {sub:.2f} is {exp:.2f}"


def r_totals(p, f, ctx):
    tol = float(p.get("tolerance", 0.05))
    sub, vat, tot = _f(f, "subtotal"), _f(f, "vat_amount"), _f(f, "total")
    problems = []
    items = [to_number(i.get("line_total")) for i in f.get("line_items") or []]
    items = [x for x in items if x is not None]
    if items and sub is not None and not _close(sum(items), sub, tol):
        problems.append(f"line items add up to {sum(items):.2f} but subtotal is {sub:.2f}")
    if None not in (sub, vat, tot) and not _close(sub + vat, tot, tol):
        problems.append(f"subtotal {sub:.2f} + VAT {vat:.2f} is {sub + vat:.2f} but total is {tot:.2f}")
    if sub is None or tot is None:
        return "skip", "amounts missing"
    return ("fail", "; ".join(problems)) if problems else ("pass", "totals agree")


def r_line_math(p, f, ctx):
    tol = float(p.get("tolerance", 0.05))
    bad = []
    for n, it in enumerate(f.get("line_items") or [], 1):
        q, u, t = to_number(it.get("quantity")), to_number(it.get("unit_price")), to_number(it.get("line_total"))
        if None not in (q, u, t) and not _close(q * u, t, tol):
            bad.append(f"line {n}: {q:g} x {u:.2f} is {q * u:.2f}, not {t:.2f}")
    if not f.get("line_items"):
        return "skip", "no line items"
    return ("fail", "; ".join(bad)) if bad else ("pass", "line totals agree")


def r_date_valid(p, f, ctx):
    name = p.get("field", "issue_date")
    d = parse_date(f.get(name))
    if not d:
        return ("skip", f"{name} missing") if not f.get(name) else ("fail", f"{name} '{f.get(name)}' is not a date")
    day = date.fromisoformat(d)
    if p.get("not_future", True) and day > ctx.today:
        return "fail", f"{name} {d} is in the future"
    age = int(p.get("max_age_days", 0) or 0)
    if age and day < ctx.today - timedelta(days=age):
        return "fail", f"{name} {d} is older than {age} days"
    return "pass", d


def r_date_order(p, f, ctx):
    a, b = parse_date(f.get(p.get("first", "issue_date"))), parse_date(f.get(p.get("second", "due_date")))
    if not a or not b:
        return "skip", "a date is missing"
    return ("pass", "in order") if a <= b else ("fail", f"{p.get('second', 'due_date')} {b} is before {a}")


def r_currency(p, f, ctx):
    allowed = [str(x).upper() for x in p.get("allowed", ["SAR"])]
    v = str(f.get("currency") or "").strip()
    if not v:
        return "skip", "currency missing"
    return ("pass", v) if v.upper() in allowed else ("fail", f"currency {v} not in {', '.join(allowed)}")


def r_amount_limit(p, f, ctx):
    name = p.get("field", "total")
    v = _f(f, name)
    if v is None:
        return "skip", f"{name} missing"
    mx, mn = p.get("max", 50000), p.get("min")
    if mn not in (None, "") and v < float(mn):
        return "fail", f"{name} {v:.2f} is below {float(mn):,.0f}"
    if mx not in (None, "") and v > float(mx):
        return "fail", f"{name} {v:.2f} exceeds {float(mx):,.0f}"
    return "pass", f"{v:.2f} within limit"


def r_qr_match(p, f, ctx):
    payload = f.get("qr_payload")
    if not payload:
        return ("fail", "no QR payload") if p.get("required") else ("skip", "no QR payload")
    q = qr.decode(payload)
    if not q:
        return "fail", "QR payload is not valid TLV base64"
    problems = []
    if vat_key(q.get("seller_vat")) != vat_key(f.get("seller_vat")):
        problems.append(f"QR VAT {q.get('seller_vat')} vs printed {f.get('seller_vat')}")
    for key, name in (("total", "total"), ("vat_amount", "vat_amount")):
        a, b = to_number(q.get(key)), _f(f, name)
        if a is not None and b is not None and not _close(a, b, 0.01):
            problems.append(f"QR {name} {a:.2f} vs printed {b:.2f}")
    sn, qn = (f.get("seller_name") or "").casefold().strip(), q.get("seller_name", "").casefold().strip()
    has_ar = lambda t: any("\u0600" <= c <= "\u06ff" for c in t)
    # a registered name may be printed in Arabic and encoded in English (or the reverse), so only compare like with like
    if sn and qn and has_ar(sn) == has_ar(qn) and qn not in sn and sn not in qn:
        problems.append("QR seller name differs from printed name")
    return ("fail", "; ".join(problems)) if problems else ("pass", "QR agrees with printed values")


def r_duplicate(p, f, ctx):
    vat, num = f.get("seller_vat"), f.get("invoice_number")
    if not vat or not num:
        return "skip", "seller VAT or invoice number missing"
    return ("fail", f"invoice {num} from {vat} was already received") if ctx.is_duplicate(str(vat), str(num)) else ("pass", "first time seen")


def r_min_confidence(p, f, ctx):
    t = float(p.get("threshold", 0.85))
    return ("pass", f"{ctx.confidence:.2f}") if ctx.confidence >= t else ("fail", f"extraction confidence {ctx.confidence:.2f} below {t:.2f}")


# ---- safe expressions -------------------------------------------------------------------

_MAX_EXPR = 300
_NAMES = set(SCALARS) | {"item_count", "today", "confidence", "line_items"}


def _sum_of(items, key):
    return sum(x for x in (to_number(i.get(key)) for i in items) if x is not None)


FUNCS = {
    "abs": abs, "round": round, "min": min, "max": max, "len": len,
    "lower": lambda s: str(s).casefold(), "upper": lambda s: str(s).upper(),
    "contains": lambda a, b: str(b).casefold() in str(a).casefold(),
    "digits": lambda s: re.sub(r"\D", "", str(s)),
}
HELP_FUNCS = list(FUNCS) + ["sum_of"]

_BIN = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod)
_CMP = (ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn)


def validate_expression(expr: str) -> None:
    if not expr or len(expr) > _MAX_EXPR:
        raise ValueError(f"expression must be 1 to {_MAX_EXPR} characters")
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"syntax error: {exc.msg}") from exc
    for node in ast.walk(tree):
        if isinstance(node, (ast.Expression, ast.BoolOp, ast.And, ast.Or, ast.Not, ast.USub, ast.UnaryOp,
                             ast.Load, ast.IfExp, ast.List, ast.Tuple, ast.BinOp, ast.Compare, ast.Constant)):
            continue
        if isinstance(node, _BIN) or isinstance(node, _CMP):
            continue
        if isinstance(node, ast.Name):
            if node.id not in _NAMES and node.id not in FUNCS and node.id != "sum_of":
                raise ValueError(f"unknown name '{node.id}'. Fields: {', '.join(sorted(_NAMES))}")
            continue
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or (node.func.id not in FUNCS and node.func.id != "sum_of") or node.keywords:
                raise ValueError("only the built-in helper functions can be called: " + ", ".join(HELP_FUNCS))
            continue
        raise ValueError(f"'{type(node).__name__}' is not allowed in expressions")
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and not isinstance(node.value, (int, float, str, bool, type(None))):
            raise ValueError("unsupported constant")


def _ev(node, env, items):
    if isinstance(node, ast.Expression):
        return _ev(node.body, env, items)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return env[node.id]
    if isinstance(node, ast.BoolOp):
        vals = (_ev(v, env, items) for v in node.values)
        return all(vals) if isinstance(node.op, ast.And) else any(vals)
    if isinstance(node, ast.UnaryOp):
        v = _ev(node.operand, env, items)
        return (not v) if isinstance(node.op, ast.Not) else -v
    if isinstance(node, ast.BinOp):
        a, b = _ev(node.left, env, items), _ev(node.right, env, items)
        if isinstance(a, bool) or isinstance(b, bool) or not all(isinstance(x, (int, float)) for x in (a, b)):
            raise TypeError("arithmetic needs numbers")
        op = node.op
        return a + b if isinstance(op, ast.Add) else a - b if isinstance(op, ast.Sub) else a * b if isinstance(op, ast.Mult) \
            else a / b if isinstance(op, ast.Div) else a % b
    if isinstance(node, ast.Compare):
        left = _ev(node.left, env, items)
        for op, right_node in zip(node.ops, node.comparators):
            right = _ev(right_node, env, items)
            ok = (left == right if isinstance(op, ast.Eq) else left != right if isinstance(op, ast.NotEq)
                  else left < right if isinstance(op, ast.Lt) else left <= right if isinstance(op, ast.LtE)
                  else left > right if isinstance(op, ast.Gt) else left >= right if isinstance(op, ast.GtE)
                  else left in right if isinstance(op, ast.In) else left not in right)
            if not ok:
                return False
            left = right
        return True
    if isinstance(node, ast.IfExp):
        return _ev(node.body, env, items) if _ev(node.test, env, items) else _ev(node.orelse, env, items)
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_ev(e, env, items) for e in node.elts]
    if isinstance(node, ast.Call):
        args = [_ev(a, env, items) for a in node.args]
        if node.func.id == "sum_of":
            return _sum_of(args[0] or [], args[1])
        return FUNCS[node.func.id](*args)
    raise ValueError("unsupported expression")


def r_expression(p, f, ctx):
    expr = p.get("expr", "")
    validate_expression(expr)
    items = f.get("line_items") or []
    env = {k: _f(f, k) for k in SCALARS}
    env.update(item_count=len(items), today=ctx.today.isoformat(), confidence=ctx.confidence, line_items=items)
    try:
        ok = bool(_ev(ast.parse(expr, mode="eval"), env, items))
    except (TypeError, ZeroDivisionError):
        return "fail", "could not evaluate, a field it needs is missing or the wrong type"
    return ("pass", "condition holds") if ok else ("fail", f"condition not met: {expr}")


RULE_TYPES: dict[str, dict] = {
    "required_fields": dict(fn=r_required_fields, label="Required fields", description="Every listed field must have a value.",
                            params=[dict(name="fields", kind="list", default=["invoice_number", "issue_date", "seller_name", "seller_vat", "currency", "subtotal", "vat_amount", "total"], help="Field names")]),
    "regex": dict(fn=r_regex, label="Field matches a pattern", description="A field must fully match a regular expression.",
                  params=[dict(name="field", kind="field", default="invoice_number"), dict(name="pattern", kind="text", default=r"[A-Z0-9\-/]{3,30}")]),
    "vat_number": dict(fn=r_vat_number, label="VAT number format", description="15 digits, starting and ending with 3.",
                       params=[dict(name="field", kind="field", default="seller_vat"), dict(name="optional", kind="bool", default=False)]),
    "vat_rate": dict(fn=r_vat_rate, label="VAT rate", description="VAT amount must equal the rate times the subtotal.",
                     params=[dict(name="rate", kind="number", default=0.15), dict(name="tolerance", kind="number", default=0.05)]),
    "totals": dict(fn=r_totals, label="Totals add up", description="Line items sum to the subtotal and subtotal plus VAT equals the total.",
                   params=[dict(name="tolerance", kind="number", default=0.05)]),
    "line_math": dict(fn=r_line_math, label="Line arithmetic", description="Quantity times unit price equals each line total.",
                      params=[dict(name="tolerance", kind="number", default=0.05)]),
    "date_valid": dict(fn=r_date_valid, label="Date is valid", description="A real date, optionally not in the future and not too old.",
                       params=[dict(name="field", kind="field", default="issue_date"), dict(name="not_future", kind="bool", default=True), dict(name="max_age_days", kind="number", default=0)]),
    "date_order": dict(fn=r_date_order, label="Date order", description="The first date must not be after the second.",
                       params=[dict(name="first", kind="field", default="issue_date"), dict(name="second", kind="field", default="due_date")]),
    "currency": dict(fn=r_currency, label="Allowed currencies", description="Currency must be one of the listed codes.",
                     params=[dict(name="allowed", kind="list", default=["SAR"])]),
    "amount_limit": dict(fn=r_amount_limit, label="Amount limit", description="A numeric field must stay at or above a minimum and at or below a maximum.",
                         params=[dict(name="field", kind="field", default="total"),
                                 dict(name="min", kind="number", default=None, optional=True, help="leave empty for no lower limit"),
                                 dict(name="max", kind="number", default=50000, optional=True, help="leave empty for no upper limit")]),
    "qr_match": dict(fn=r_qr_match, label="QR code agrees", description="The QR payload must match the printed VAT number, total and VAT.",
                     params=[dict(name="required", kind="bool", default=False)]),
    "duplicate": dict(fn=r_duplicate, label="Duplicate invoice", description="The same seller VAT number and invoice number must not be received twice.", params=[]),
    "min_confidence": dict(fn=r_min_confidence, label="Extraction confidence", description="Overall confidence of the extraction must reach a threshold.",
                           params=[dict(name="threshold", kind="number", default=0.85)]),
    "expression": dict(fn=r_expression, label="Custom expression", description="Write your own condition. It must be true for the invoice to pass.",
                       params=[dict(name="expr", kind="text", default="total <= 100000 and item_count > 0")]),
}


def validate_rule(rule: dict) -> None:
    """Raise ValueError with a message an admin can act on."""
    t = rule.get("type")
    if t not in RULE_TYPES:
        raise ValueError(f"unknown rule type '{t}'")
    if rule.get("severity") not in SEVERITIES:
        raise ValueError("severity must be reject, review or info")
    if not (rule.get("name") or "").strip():
        raise ValueError("a rule needs a name")
    p = rule.get("params") or {}
    for spec in RULE_TYPES[t]["params"]:
        if spec["kind"] == "field" and p.get(spec["name"], spec["default"]) not in FIELDS:
            raise ValueError(f"{spec['name']} must be one of: {', '.join(FIELDS)}")
        if spec["kind"] == "number":
            value = p.get(spec["name"], spec["default"])
            if spec.get("optional") and value in (None, ""):
                continue
            try:
                float(value)
            except (TypeError, ValueError):
                raise ValueError(f"{spec['name']} must be a number") from None
        if spec["kind"] == "list" and not isinstance(p.get(spec["name"], spec["default"]), list):
            raise ValueError(f"{spec['name']} must be a list")
    if t == "regex":
        try:
            re.compile(p.get("pattern", ""))
        except re.error as exc:
            raise ValueError(f"invalid pattern: {exc}") from exc
    if t == "required_fields":
        bad = [x for x in p.get("fields", []) if x not in FIELDS]
        if bad:
            raise ValueError(f"unknown fields: {', '.join(bad)}")
    if t == "expression":
        validate_expression(p.get("expr", ""))


def run_rules(rules: list[dict], fields: dict, ctx: Ctx) -> list[dict]:
    out = []
    for r in rules:
        if not r.get("enabled", True):
            continue
        try:
            status, detail = RULE_TYPES[r["type"]]["fn"](r.get("params") or {}, fields, ctx)
        except Exception as exc:  # a broken rule must not take the pipeline down
            status, detail = "fail", f"rule error: {exc}"
        if status == "fail" and r.get("message"):
            detail = f"{r['message']} ({detail})"
        out.append(dict(key=r["key"], name=r["name"], severity=r["severity"], status=status, detail=detail))
    return out


def decide(results: list[dict]) -> str:
    failed = [x for x in results if x["status"] == "fail"]
    if any(x["severity"] == "reject" for x in failed):
        return "rejected"
    if any(x["severity"] == "review" for x in failed):
        return "needs_review"
    return "approved"
