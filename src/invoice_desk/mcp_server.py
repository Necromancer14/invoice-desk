"""MCP server: lets any MCP client (Claude Desktop, Claude Code) check invoices against the rules.

Run:  python -m invoice_desk.mcp_server        (stdio)
Uses the default rule set and the rule-based reader, so it needs no API key and keeps no data.
"""
from __future__ import annotations

import json
from datetime import date

from mcp.server.mcpserver import MCPServer

from .default_rules import DEFAULT_RULES
from .extractors import RuleBasedExtractor
from .rules import RULE_TYPES, Ctx, decide, run_rules
from .schema import FIELDS, empty_fields

mcp = MCPServer("invoice-desk")
_RULES = [dict(r, enabled=True) for r in DEFAULT_RULES]


@mcp.tool()
def read_invoice_text(text: str) -> dict:
    """Pull the standard fields (invoice number, dates, seller, VAT numbers, totals, line items) out of plain-text invoice content."""
    ext = RuleBasedExtractor().parse(text)
    fields, notes = ext
    return {"fields": fields, "notes": notes}


@mcp.tool()
def check_invoice(fields_json: str, today: str | None = None) -> dict:
    """Run the Saudi e-invoice rules (VAT number format, 15% VAT, totals, dates, currency, limits) on extracted fields.

    fields_json is a JSON object using the field names from list_fields. Returns approved, needs_review or rejected, plus each rule's result.
    """
    data = json.loads(fields_json)
    fields = {**empty_fields(), **{k: v for k, v in data.items() if k in FIELDS}}
    results = run_rules(_RULES, fields, Ctx(today=date.fromisoformat(today) if today else date.today()))
    return {"decision": decide(results), "results": results}


@mcp.tool()
def list_fields() -> list[str]:
    """The field names check_invoice understands."""
    return FIELDS


@mcp.tool()
def explain_rules() -> list[dict]:
    """Describe the rules that check_invoice applies and what each does when it fails."""
    return [{"name": r["name"], "type": RULE_TYPES[r["type"]]["label"], "if_fails": r["severity"], "params": r["params"]} for r in _RULES]


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
