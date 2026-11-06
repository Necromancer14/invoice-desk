import json

import pytest

pytest.importorskip("mcp")
from invoice_desk import mcp_server as m  # noqa: E402
from conftest import GOOD  # noqa: E402


def test_mcp_read_then_check():
    fields = m.read_invoice_text(GOOD)["fields"]
    out = m.check_invoice(json.dumps(fields), "2026-11-05")
    assert out["decision"] == "approved"
    fields["vat_amount"] = 10.0
    assert m.check_invoice(json.dumps(fields), "2026-11-05")["decision"] == "rejected"


def test_mcp_lists_rules():
    assert len(m.explain_rules()) == len(m._RULES) == 20 and "total" in m.list_fields()
