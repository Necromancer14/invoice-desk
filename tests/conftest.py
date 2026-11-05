import os
from datetime import date

import pytest

os.environ["INVOICE_DESK_AUTOCREATE"] = "0"

from invoice_desk.auth import Auth  # noqa: E402
from invoice_desk.desk import Desk  # noqa: E402

TODAY = date(2026, 11, 5)

GOOD = """TAX INVOICE
Invoice No: ACM-2026-0001
Issue Date: 2026-10-01
Due Date: 2026-11-01
Seller: Acme Trading
Seller VAT No: 300000000000003
Buyer: Beta Foods
Currency: SAR

Description   Qty   Unit price   Total
1. Consulting   2   500.00   1,000.00

Subtotal: 1,000.00 SAR
VAT (15%): 150.00 SAR
Total (including VAT): 1,150.00 SAR
"""


@pytest.fixture
def desk():
    return Desk(":memory:", today=TODAY, sync=True)


@pytest.fixture
def auth():
    return Auth(secret="test-secret", demo=True, users="boss:pw:admin")


@pytest.fixture
def good():
    return GOOD.encode()
