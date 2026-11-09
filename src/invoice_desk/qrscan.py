"""Reads QR codes from invoice images and PDF pages.

Scope, stated plainly: clean, digitally made codes (a PDF, a screenshot, a rendered invoice), upright or turned by a
right angle. Not phone photos taken at an angle, blurred or bent codes.

No maintained pure-Python QR *reader* is known, so this is a small one. It finds the three finder squares, samples the
grid, reads the format and the data, and then re-encodes what it read with the pure-Python `qrcode` package: a read
only counts if that draws the same code (allowing a few stray modules). That check stands in for Reed-Solomon error
correction, which is not done here.
"""
from __future__ import annotations

import io
import math
import re
from itertools import combinations

from qrcode import util
from qrcode.base import rs_blocks
from qrcode.exceptions import DataOverflowError
from qrcode.main import QRCode

_RUN = re.compile(rb"1+|0+")
MAX_SIDE = 3000          # larger images are scaled down first
PDF_SCALE = 2.5          # PDF pages are drawn at 180 dpi when no embedded image holds the code
MAX_PDF_PAGES = 3


# ---- finding the three finder squares ----------------------------------------------------------
def _five_ok(r) -> bool:
    """Run lengths in the 1:1:3:1:1 proportion of a finder square."""
    total = sum(r)
    if total < 7:
        return False
    m = total / 7
    v = m / 2
    return abs(m - r[0]) < v and abs(m - r[1]) < v and abs(3 * m - r[2]) < 3 * v and abs(m - r[3]) < v and abs(m - r[4]) < v


def _cross(bits: bytes, w: int, h: int, x: int, y: int, dx: int, dy: int, limit: int):
    """Along a line through (x, y) that starts in the dark centre: the five runs and the centre's middle, or None."""
    def at(i, j):
        return 0 <= i < w and 0 <= j < h and bits[j * w + i] == 49

    def walk(sx, sy, colour, step):
        n = 0
        while at(x + sx * (n + step), y + sy * (n + step)) == colour and n < limit:
            n += 1
        return n
    if not at(x, y):
        return None
    back = [0, 0, 0]
    fwd = [0, 0, 0]
    # centre run
    back[0] = walk(-dx, -dy, True, 0)
    fwd[0] = walk(dx, dy, True, 1)
    off_b, off_f = back[0], fwd[0]
    for k, colour in ((1, False), (2, True)):
        n = 0
        while at(x - dx * (off_b + n), y - dy * (off_b + n)) == colour and n < limit:
            n += 1
        back[k], off_b = n, off_b + n
        n = 0
        while at(x + dx * (off_f + 1 + n), y + dy * (off_f + 1 + n)) == colour and n < limit:
            n += 1
        fwd[k], off_f = n, off_f + n
    runs = [back[2], back[1], back[0] + fwd[0], fwd[1], fwd[2]]
    if not all(runs) or not _five_ok(runs):
        return None
    # the centre run covers pixels x - back[0] + 1 .. x + fwd[0]; pixel i spans [i, i + 1), so its middle is:
    return (fwd[0] - back[0] + 2) / 2, sum(runs)


def _finders(bits: bytes, w: int, h: int) -> list[tuple[float, float, float, int]]:
    """Finder square centres as (x, y, module size, hits), most-confirmed first."""
    found: list[list[float]] = []
    for y in range(0, h, 2):
        row = bits[y * w:(y + 1) * w]
        runs = [(m.start(), m.end(), m.group()[0] == 49) for m in _RUN.finditer(row)]
        for i in range(len(runs) - 4):
            if not runs[i][2]:
                continue
            five = runs[i:i + 5]
            lengths = [e - s for s, e, _ in five]
            if not _five_ok(lengths):
                continue
            cx = int((five[2][0] + five[2][1]) / 2)
            v = _cross(bits, w, h, cx, y, 0, 1, sum(lengths) * 2)
            if not v or abs(v[1] - sum(lengths)) > 0.4 * sum(lengths):
                continue
            cy = y + v[0]
            hz = _cross(bits, w, h, cx, int(cy), 1, 0, sum(lengths) * 2)
            if not hz:
                continue
            x = cx + hz[0]
            module = (hz[1] + v[1]) / 14
            for f in found:
                if abs(f[0] - x) < 2 * module and abs(f[1] - cy) < 2 * module:
                    f[0] = (f[0] * f[3] + x) / (f[3] + 1)
                    f[1] = (f[1] * f[3] + cy) / (f[3] + 1)
                    f[2] = (f[2] * f[3] + module) / (f[3] + 1)
                    f[3] += 1
                    break
            else:
                found.append([x, cy, module, 1])
    return sorted((tuple(f) for f in found if f[3] >= 2), key=lambda f: -f[3])[:12]


def _triples(finders):
    """Sets of three finder squares that form a QR code's corner, best first, as (top-left, top-right, bottom-left)."""
    out = []
    for a, b, c in combinations(finders, 3):
        mods = (a[2], b[2], c[2])
        if max(mods) > 1.4 * min(mods):
            continue
        pts = (a, b, c)
        sides = sorted(((math.dist(pts[i][:2], pts[j][:2]), k) for k, (i, j) in enumerate(((1, 2), (0, 2), (0, 1)))))
        (s1, _), (s2, _), (long, corner) = sides
        if s1 < 10 * min(mods) or s2 > 1.25 * s1 or abs(long / math.hypot(s1, s2) - 1) > 0.1:
            continue
        tl = pts[corner]
        p, q = (pts[i] for i in range(3) if i != corner)
        # in image coordinates (y down), top-right then bottom-left turns clockwise
        if (p[0] - tl[0]) * (q[1] - tl[1]) - (p[1] - tl[1]) * (q[0] - tl[0]) < 0:
            p, q = q, p
        out.append((abs(s2 / s1 - 1) + abs(long / math.hypot(s1, s2) - 1), tl, p, q))
    return [t[1:] for t in sorted(out, key=lambda t: t[0])]


# ---- reading the grid --------------------------------------------------------------------------
def _sample(bits: bytes, w: int, h: int, tl, tr, bl, dim: int):
    span = dim - 7
    ux, uy = (tr[0] - tl[0]) / span, (tr[1] - tl[1]) / span
    vx, vy = (bl[0] - tl[0]) / span, (bl[1] - tl[1]) / span
    q = 0.22  # five probes per module, a little in from its edges
    probes = ((0, 0), (-q, -q), (q, -q), (-q, q), (q, q))
    grid = []
    for r in range(dim):
        row = []
        for c in range(dim):
            dark = 0
            for pc, pr in probes:
                mc, mr = c + 0.5 + pc - 3.5, r + 0.5 + pr - 3.5
                x, y = int(tl[0] + mc * ux + mr * vx), int(tl[1] + mc * uy + mr * vy)
                dark += 0 <= x < w and 0 <= y < h and bits[y * w + x] == 49
            row.append(dark >= 3)
        grid.append(row)
    return grid


def _format(grid, dim: int):
    """(error correction level, mask) from the format bits, trying both copies; None if neither is close enough."""
    vertical = [(i, 8) if i < 6 else (i + 1, 8) if i < 8 else (dim - 15 + i, 8) for i in range(15)]
    horizontal = [(8, dim - i - 1) if i < 8 else (8, 15 - i) if i < 9 else (8, 15 - i - 1) for i in range(15)]
    for cells in (vertical, horizontal):
        read = sum(grid[r][c] << i for i, (r, c) in enumerate(cells))
        best = min(range(32), key=lambda d: bin(util.BCH_type_info(d) ^ read).count("1"))
        if bin(util.BCH_type_info(best) ^ read).count("1") <= 3:
            return best >> 3, best & 7
    return None


def _blank(version: int, ec: int, mask: int) -> QRCode:
    q = QRCode(version=version, error_correction=ec, mask_pattern=mask, border=0)
    n = q.modules_count = version * 4 + 17
    q.modules = [[None] * n for _ in range(n)]
    q.setup_position_probe_pattern(0, 0)
    q.setup_position_probe_pattern(n - 7, 0)
    q.setup_position_probe_pattern(0, n - 7)
    q.setup_position_adjust_pattern()
    q.setup_timing_pattern()
    q.setup_type_info(False, mask)
    if version >= 7:
        q.setup_type_number(False)
    return q


def _codewords(grid, version: int, ec: int, mask: int) -> bytes:
    """The data cells in the order the standard lays them out (the same walk as qrcode's map_data), unmasked."""
    blank = _blank(version, ec, mask).modules
    n = len(blank)
    masked = util.mask_func(mask)
    out, byte, nbits = bytearray(), 0, 0
    row, inc = n - 1, -1
    for col in range(n - 1, 0, -2):
        if col <= 6:
            col -= 1
        while True:
            for c in (col, col - 1):
                if blank[row][c] is None:
                    bit = grid[row][c] ^ bool(masked(row, c))
                    byte, nbits = (byte << 1) | bit, nbits + 1
                    if nbits == 8:
                        out.append(byte)
                        byte, nbits = 0, 0
            row += inc
            if row < 0 or row >= n:
                row -= inc
                inc = -inc
                break
    return bytes(out)


def _segments(codewords: bytes, version: int, ec: int):
    """De-interleave the blocks and read the data segments as [(mode, bytes)]."""
    counts = [b.data_count for b in rs_blocks(version, ec)]
    blocks: list[list[int]] = [[] for _ in counts]
    i = 0
    for k in range(max(counts)):
        for b, dc in enumerate(counts):
            if k < dc:
                if i >= len(codewords):
                    return None
                blocks[b].append(codewords[i])
                i += 1
    data = bytes(x for block in blocks for x in block)
    bits = "".join(f"{x:08b}" for x in data)
    pos, segs = 0, []

    def take(n):
        nonlocal pos
        if pos + n > len(bits):
            raise ValueError("ran out of data")
        v = int(bits[pos:pos + n], 2)
        pos += n
        return v
    try:
        while pos + 4 <= len(bits):
            mode = take(4)
            if mode == 0:
                break
            if mode == 7:  # ECI designator: one byte is enough for the common ones
                take(8)
                continue
            if mode not in (util.MODE_NUMBER, util.MODE_ALPHA_NUM, util.MODE_8BIT_BYTE):
                return None
            count = take(util.length_in_bits(mode, version))
            if mode == util.MODE_8BIT_BYTE:
                chunk = bytes(take(8) for _ in range(count))
            elif mode == util.MODE_ALPHA_NUM:
                chars = []
                for _ in range(count // 2):
                    v = take(11)
                    chars += [util.ALPHA_NUM[v // 45], util.ALPHA_NUM[v % 45]]
                if count % 2:
                    chars.append(util.ALPHA_NUM[take(6)])
                chunk = bytes(chars)
            else:
                digits = ""
                for _ in range(count // 3):
                    digits += f"{take(10):03d}"
                rest = count % 3
                if rest:
                    digits += f"{take(7 if rest == 2 else 4):0{rest}d}"
                chunk = digits.encode()
            segs.append((mode, chunk))
    except (ValueError, IndexError):
        return None
    return segs


def _verified(grid, version: int, ec: int, mask: int, segs) -> bool:
    """Re-encode what was read; it must draw (almost) the same code."""
    q = QRCode(version=version, error_correction=ec, mask_pattern=mask, border=0)
    for mode, chunk in segs:
        q.add_data(util.QRData(chunk, mode=mode, check_data=False))
    try:
        q.make(fit=False)
    except (DataOverflowError, ValueError, TypeError):
        return False
    n = len(grid)
    wrong = sum(q.modules[r][c] != grid[r][c] for r in range(n) for c in range(n))
    return wrong <= 0.02 * n * n


def read_image(img) -> str | None:
    """The text of the first QR code found in a PIL image, or None."""
    if max(img.size) > MAX_SIDE:
        img = img.copy()
        img.thumbnail((MAX_SIDE, MAX_SIDE))
    if img.mode in ("RGBA", "LA", "P"):
        from PIL import Image
        bg = Image.new("RGB", img.size, "white")
        bg.paste(img.convert("RGBA"), mask=img.convert("RGBA").getchannel("A"))
        img = bg
    gray = img.convert("L")
    w, h = gray.size
    bits = gray.point(lambda p: 49 if p < 128 else 48).tobytes()
    for tl, tr, bl in _triples(_finders(bits, w, h))[:6]:
        module = (tl[2] + tr[2] + bl[2]) / 3
        span = (math.dist(tl[:2], tr[:2]) + math.dist(tl[:2], bl[:2])) / 2
        guess = round((span / module + 7 - 17) / 4)
        for version in sorted({guess, guess - 1, guess + 1}, key=lambda v: abs(v - guess)):
            if not 1 <= version <= 40:
                continue
            dim = 17 + 4 * version
            grid = _sample(bits, w, h, tl, tr, bl, dim)
            fmt = _format(grid, dim)
            if not fmt:
                continue
            ec, mask = fmt
            segs = _segments(_codewords(grid, version, ec, mask), version, ec)
            if segs and _verified(grid, version, ec, mask, segs):
                return b"".join(chunk for _, chunk in segs).decode("utf-8", "replace")
    return None


def find_in_file(blob: bytes, content_type: str) -> str | None:
    """The first QR code in an image file or in the first pages of a PDF, or None."""
    from PIL import Image
    if content_type.startswith("image/"):
        with Image.open(io.BytesIO(blob)) as img:
            img.load()
            return read_image(img)
    if content_type != "application/pdf":
        return None
    try:  # images embedded in the PDF are the sharpest source
        from pypdf import PdfReader
        for page in PdfReader(io.BytesIO(blob)).pages[:MAX_PDF_PAGES]:
            for embedded in page.images:
                text = read_image(embedded.image)
                if text:
                    return text
    except Exception:  # noqa: BLE001 - fall back to drawing the page
        pass
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(blob)
    for i in range(min(len(pdf), MAX_PDF_PAGES)):
        text = read_image(pdf[i].render(scale=PDF_SCALE).to_pil())
        if text:
            return text
    return None
