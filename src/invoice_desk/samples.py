from __future__ import annotations

from pathlib import Path

from .evaluation import SAMPLES, load_answers

LABELS = {"clean": "Clean invoice", "prompt_injection": "Hidden instruction inside the invoice", "bad_vat": "Malformed seller VAT number",
          "vat_rate": "Wrong VAT rate", "totals": "Totals do not add up", "future_date": "Issue date in the future",
          "duplicate": "Duplicate of an earlier invoice", "qr_mismatch": "QR code disagrees with printed total",
          "non_sar": "Foreign currency", "over_limit": "High value invoice", "missing_vat": "Seller VAT number missing",
          "due_before_issue": "Due date before issue date"}


def list_samples(root: Path = SAMPLES) -> list[dict]:
    out = []
    for it in load_answers(root)["invoices"]:
        out.append(dict(id=it["id"], file=it["file"], format=it["format"], lang=it["lang"], scenario=it["scenario"],
                        label=LABELS.get(it["scenario"], it["scenario"]), vision_only=it["vision_only"]))
    return out


def sample_bytes(file: str, root: Path = SAMPLES) -> bytes:
    p = (root / file).resolve()
    if root.resolve() not in p.parents or not p.is_file():
        raise FileNotFoundError(file)
    return p.read_bytes()
