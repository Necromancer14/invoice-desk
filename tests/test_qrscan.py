"""The QR reader: generated codes, sizes, turns, a PDF, and QR checks end to end on uploaded images."""
import io

import pytest
import qrcode
from PIL import Image, ImageDraw

from invoice_desk import qr
from invoice_desk.desk import Desk
from invoice_desk.qrscan import find_in_file, read_image
from conftest import TODAY

PAYLOAD = qr.encode("Najd Office Supplies Co.", "300000000000003", "2026-10-01T09:30:00Z", 1150.0, 150.0)


def page_with(code_img, scale=1.0, rotate=0, size=(1000, 1000)):
    page = Image.new("RGB", size, "white")
    d = ImageDraw.Draw(page)
    for y in range(20, size[1] - 20, 18):  # text-like clutter around the code
        d.text((20, y), "Invoice line 1234  SAR 1,150.00  ||| ## ::", fill="black")
    im = code_img.convert("RGB").rotate(rotate, expand=True)
    if scale != 1:
        im = im.resize((round(im.width * scale), round(im.height * scale)), Image.BICUBIC)
    page.paste(im, (size[0] - im.width - 40, 60))
    return page


@pytest.mark.parametrize("text", ["HELLO", "12345678901234567890", PAYLOAD,
                                  qr.encode("شركة نجد للمستلزمات المكتبية", "312345678901233", "2026-10-01T09:30:00Z", 123456.78, 16103.06)])
@pytest.mark.parametrize("box, ec", [(2, qrcode.constants.ERROR_CORRECT_M), (3, qrcode.constants.ERROR_CORRECT_L), (5, qrcode.constants.ERROR_CORRECT_Q)])
def test_reads_generated_codes(text, box, ec):
    img = qrcode.make(text, box_size=box, border=2, error_correction=ec)
    assert read_image(page_with(img)) == text


@pytest.mark.parametrize("rotate", [90, 180, 270])
@pytest.mark.parametrize("scale", [1.0, 1.4])
def test_reads_turned_and_scaled_codes(rotate, scale):
    img = qrcode.make(PAYLOAD, box_size=4, border=2)
    assert read_image(page_with(img, scale=scale, rotate=rotate)) == PAYLOAD


def test_nothing_is_invented_on_a_page_without_a_code():
    assert read_image(Image.new("RGB", (800, 800), "white")) is None
    assert read_image(page_with(Image.new("RGB", (10, 10), "white"))) is None


def test_reads_a_code_inside_a_pdf():
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(595, 842))
    c.drawString(60, 780, "TAX INVOICE  Invoice No: A-1")
    c.drawImage(ImageReader(qrcode.make(PAYLOAD, box_size=4, border=2).get_image()), 60, 560, width=150, height=150)
    c.save()
    assert find_in_file(buf.getvalue(), "application/pdf") == PAYLOAD


def png_bytes(img) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


@pytest.mark.parametrize("payload, qr_status", [
    (PAYLOAD, "pass"),
    (qr.encode("Najd Office Supplies Co.", "300000000000003", "2026-10-01T09:30:00Z", 9999.0, 150.0), "pass"),
    (None, "fail"),
])
def test_image_upload_reads_the_qr_code(payload, qr_status):
    desk = Desk(":memory:", today=TODAY, sync=True)
    img = page_with(qrcode.make(payload, box_size=4, border=2)) if payload else page_with(Image.new("RGB", (10, 10), "white"))
    run = desk.get_run(desk.submit("scan.png", png_bytes(img), "image/png", "t"))
    assert run["extracted"]["qr_payload"] == payload
    steps = {s["step"]: s for s in run["trace"]}
    assert steps["qr"]["ok"] == bool(payload)
    present = next(r for r in run["results"] if r["key"] == "qr-present")
    assert present["status"] == qr_status and present["severity"] == "info"


def test_qr_disagreeing_with_the_printed_invoice_is_flagged(desk):
    """A text invoice whose QR total differs, and a QR whose date is a day off in Saudi time."""
    from conftest import GOOD
    wrong_total = qr.encode("Acme Trading", "300000000000003", "2026-10-01T09:30:00Z", 1999.0, 150.0)
    late = qr.encode("Acme Trading", "300000000000003", "2026-10-01T22:30:00Z", 1150.0, 150.0)  # 01:30 on 2 Oct in Riyadh
    for payload, words in ((wrong_total, "QR total"), (late, "QR date 2026-10-02")):
        run = desk.get_run(desk.submit("a.txt", (GOOD + f"QR: {payload}\n").replace("ACM-2026-0001", f"N-{words[:4]}").encode(), "text/plain", "t"))
        check = next(r for r in run["results"] if r["key"] == "qr-agrees")
        assert check["status"] == "fail" and words in check["detail"], check
