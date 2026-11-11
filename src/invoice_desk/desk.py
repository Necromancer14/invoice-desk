"""The service layer: intake, pipeline, review, rules admin, stats, audit. No HTTP in here."""
from __future__ import annotations

import csv
import io
import re
import time
from pathlib import Path
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

from .db import DB, dumps, loads
from .default_rules import DEFAULT_RULES
from .extractors import IMAGE_TYPES, Extraction, NeedsVision, RuleBasedExtractor, guess_type
from .qrscan import find_in_file
from .providers import ProviderError, build_extractor
from .rules import RULE_TYPES, Ctx, decide, run_rules, validate_rule
from .schema import FIELDS, NUMERIC, SCALARS, empty_fields
from .textnorm import number_key, parse_date, to_number, vat_key
from . import ubl
from .ubl import UblExtractor, XmlError, check_safe, looks_like_xml
from .vendors import VendorBook, clean_po, clean_vendor, name_key, po_match, read_csv

SOURCES = ("upload", "evaluation")
SAMPLES_DIR = Path(__file__).resolve().parents[2] / "data" / "samples"

MAX_BYTES = 5 * 1024 * 1024
XML = "application/xml"
ALLOWED_TYPES = {"text/plain", "application/pdf", "image/png", "image/jpeg", "image/webp", "image/gif", XML}
FINAL = {"approved", "rejected", "approved_human", "rejected_human", "failed"}
# How long free text may be. Long enough for real use, short enough that nobody can fill the database through a form.
MAX_RULE_NAME, MAX_RULE_MESSAGE, MAX_VERSION_NOTE, MAX_REVIEW_NOTE = 120, 300, 500, 2000
PDF_UNREADABLE = "This PDF could not be opened. It may be damaged or not really a PDF."
DEFAULT_SETTINGS = {"default_mode": "rules", "price_in_per_mtok": "",
                    "price_out_per_mtok": "", "auto_approve": "true"}


def clean_filename(name: str | None) -> str:
    """The last part of an uploaded file's name, without control characters, at most 120 characters."""
    name = re.sub(r"[\x00-\x1f\x7f]", "", str(name or "")).replace("\\", "/").split("/")[-1].strip()
    return name[:120] or "invoice.txt"


_MAGIC = {"application/pdf": (b"%PDF",), "image/png": (b"\x89PNG\r\n\x1a\n",), "image/jpeg": (b"\xff\xd8\xff",),
          "image/gif": (b"GIF87a", b"GIF89a")}
_KIND = {"application/pdf": "a PDF", "image/png": "a PNG image", "image/jpeg": "a JPEG image", "image/gif": "a GIF image",
         "image/webp": "a WebP image", "text/plain": "a text file", "application/xml": "an XML file"}


def content_matches(ctype: str, blob: bytes) -> bool:
    """Do the first bytes fit the type the file claims? Stops, say, a program renamed to .txt or .png."""
    head = blob[:1024]
    if ctype in _MAGIC:
        return any(head.lstrip().startswith(m) if ctype == "application/pdf" else head.startswith(m) for m in _MAGIC[ctype])
    if ctype == "image/webp":
        return head[:4] == b"RIFF" and head[8:12] == b"WEBP"
    if ctype == "text/plain":
        return b"\x00" not in blob[:8192]
    if ctype == XML:
        return looks_like_xml(blob) and b"\x00" not in blob[:8192]
    return False


def friendly_error(exc: Exception) -> str:
    """What a person sees when processing fails. The technical detail stays in the trace."""
    if type(exc).__module__.split(".")[0] == "pypdf":
        return PDF_UNREADABLE
    if isinstance(exc, XmlError):
        return f"This XML file could not be read: {exc}."
    return f"{type(exc).__name__}: {exc}"[:300]


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class DeskError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class Desk:
    def __init__(self, db_path: str = ":memory:", today: date | None = None, sync: bool = False, workers: int = 2,
                 extractor_factory=None, seed_vendors: bool = False):
        """seed_vendors: fill a new database (and every reset) with the demo vendors and purchase orders from
        data/samples. The app and the evaluation do; tests start with an empty vendor master."""
        self.db = DB(db_path)
        self.today = today
        self.sync = sync
        self.pool = None if sync else ThreadPoolExecutor(max_workers=workers)
        self.extractor_factory = extractor_factory or self._default_factory
        self.seed_vendors = seed_vendors
        # every run is an upload (files and samples sent through intake) or an evaluation run; older rows said "sample"
        self.db.run("UPDATE runs SET source='upload' WHERE source IS NULL OR source NOT IN ('upload','evaluation','history')")
        if not self.db.one("SELECT key FROM rules LIMIT 1"):  # a new database: an existing one keeps its rules and vendors
            self._seed_rules()
            if seed_vendors:
                self._seed_vendor_data()

    # ---------------------------------------------------------------- helpers
    def _today(self) -> date:
        return self.today or date.today()

    def audit(self, actor: str, action: str, target: str = "", detail: str = "") -> None:
        if getattr(self, "_seeding", False):  # loading the demo vendor master is setup, not something anyone did
            return
        self.db.run("INSERT INTO audit(ts,actor,action,target,detail) VALUES(?,?,?,?,?)", (now(), actor, action, target, detail))

    def _default_factory(self, mode: str, llm: dict | None):
        if mode == "ai":
            try:
                return build_extractor(llm or {})
            except ProviderError as exc:
                raise DeskError(str(exc), 400) from exc
        return RuleBasedExtractor()

    # --------------------------------------------------------------- settings
    def settings(self) -> dict:
        out = dict(DEFAULT_SETTINGS)
        out.update({r["key"]: r["value"] for r in self.db.all("SELECT key,value FROM settings")})
        return out

    def update_settings(self, changes: dict, actor: str) -> dict:
        for k, v in changes.items():
            if k not in DEFAULT_SETTINGS:
                raise DeskError(f"unknown setting {k}")
            v = str(v).strip()
            if k == "default_mode" and v not in ("rules", "ai"):
                raise DeskError("default_mode must be rules or ai")
            if k == "auto_approve" and v not in ("true", "false"):
                raise DeskError("auto_approve must be true or false")
            if k.startswith("price_") and v != "":
                try:
                    float(v)
                except ValueError:
                    raise DeskError(f"{k} must be a number") from None
            self.db.run("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, v))
        self.audit(actor, "settings.update", "", ", ".join(changes))
        return self.settings()

    # ------------------------------------------------------------------ rules
    @staticmethod
    def _rule_row(r: dict) -> dict:
        return dict(key=r["key"], name=r["name"], type=r["type"], params=loads(r["params"], {}), severity=r["severity"],
                    enabled=bool(r["enabled"]), message=r["message"] or "", position=r["position"])

    def rules(self) -> list[dict]:
        return [self._rule_row(r) for r in self.db.all("SELECT * FROM rules ORDER BY position, key")]

    def rules_version(self) -> int:
        r = self.db.one("SELECT MAX(version) v FROM rule_versions")
        return (r or {}).get("v") or 0

    def _save_rules(self, rules: list[dict]) -> None:
        with self.db.lock:
            self.db.conn.execute("DELETE FROM rules")
            for i, r in enumerate(rules):
                self.db.conn.execute("INSERT INTO rules VALUES(?,?,?,?,?,?,?,?)",
                                     (r["key"], i, r["name"], r["type"], dumps(r.get("params") or {}), r["severity"],
                                      1 if r.get("enabled", True) else 0, r.get("message", "")))
            self.db.conn.commit()

    def _snapshot(self, author: str, note: str) -> int:
        cur = self.db.run("INSERT INTO rule_versions(snapshot,author,note,created_at) VALUES(?,?,?,?)",
                          (dumps(self.rules()), author, note, now()))
        return cur.lastrowid

    def _seed_rules(self) -> None:
        self._save_rules([dict(r, enabled=True) for r in DEFAULT_RULES])
        self._snapshot("system", "Default rule set")

    def _restore_default_rules(self) -> None:
        """The default rule set as version 1 again: earlier versions go, and so does SQLite's counter for them,
        which would otherwise carry on numbering from the highest version ever saved."""
        with self.db.lock:
            self.db.conn.execute("DELETE FROM rules")
            self.db.conn.execute("DELETE FROM rule_versions")
            self.db.conn.execute("DELETE FROM sqlite_sequence WHERE name='rule_versions'")
            self.db.conn.commit()
        self._seed_rules()

    def rule_versions(self) -> list[dict]:
        rows = self.db.all("SELECT version,author,note,created_at,snapshot FROM rule_versions ORDER BY version DESC")
        return [dict(version=r["version"], author=r["author"], note=r["note"], created_at=r["created_at"],
                     rule_count=len(loads(r["snapshot"], []))) for r in rows]

    @staticmethod
    def _slug(name: str) -> str:
        s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        return s[:40] or "rule"

    def _clean_rule(self, rule: dict) -> dict:
        r = dict(key=(rule.get("key") or "").strip(), name=(rule.get("name") or "").strip(), type=rule.get("type"),
                 params=rule.get("params") or {}, severity=rule.get("severity"), enabled=bool(rule.get("enabled", True)),
                 message=(rule.get("message") or "").strip())
        if len(r["name"]) > MAX_RULE_NAME:
            raise DeskError(f"a rule name can be at most {MAX_RULE_NAME} characters")
        if len(r["message"]) > MAX_RULE_MESSAGE:
            raise DeskError(f"the message can be at most {MAX_RULE_MESSAGE} characters")
        if not isinstance(r["params"], dict):
            raise DeskError("params must be an object")
        try:
            validate_rule(r)
        except ValueError as exc:
            raise DeskError(str(exc)) from exc
        return r

    def upsert_rule(self, rule: dict, actor: str, note: str = "") -> dict:
        r = self._clean_rule(rule)
        note = (note or "").strip()
        if len(note) > MAX_VERSION_NOTE:
            raise DeskError(f"the note can be at most {MAX_VERSION_NOTE} characters")
        current = self.rules()
        keys = {x["key"] for x in current}
        if not r["key"]:
            base = self._slug(r["name"])
            r["key"], n = base, 2
            while r["key"] in keys:
                r["key"], n = f"{base}-{n}", n + 1
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,39}", r["key"]):
            raise DeskError("key may only contain lowercase letters, digits and dashes")
        exists = r["key"] in keys
        updated = [r if x["key"] == r["key"] else x for x in current] if exists else current + [r]
        self._save_rules(updated)
        v = self._snapshot(actor, note or f"{'Edited' if exists else 'Added'} {r['name']}")
        self.audit(actor, "rule.update" if exists else "rule.create", r["key"], r["name"])
        return dict(rule=r, version=v)

    def delete_rule(self, key: str, actor: str) -> int:
        current = self.rules()
        if key not in {x["key"] for x in current}:
            raise DeskError("rule not found", 404)
        self._save_rules([x for x in current if x["key"] != key])
        v = self._snapshot(actor, f"Deleted {key}")
        self.audit(actor, "rule.delete", key)
        return v

    def reorder_rules(self, keys: list[str], actor: str) -> int:
        current = {x["key"]: x for x in self.rules()}
        if set(keys) != set(current):
            raise DeskError("reorder needs every rule key exactly once")
        self._save_rules([current[k] for k in keys])
        v = self._snapshot(actor, "Reordered rules")
        self.audit(actor, "rule.reorder")
        return v

    def rollback(self, version: int, actor: str) -> int:
        row = self.db.one("SELECT snapshot FROM rule_versions WHERE version=?", (version,))
        if not row:
            raise DeskError("version not found", 404)
        self._save_rules(loads(row["snapshot"], []))
        v = self._snapshot(actor, f"Rolled back to version {version}")
        self.audit(actor, "rule.rollback", str(version))
        return v

    def version_rules(self, version: int) -> list[dict]:
        row = self.db.one("SELECT snapshot FROM rule_versions WHERE version=?", (version,))
        if not row:
            raise DeskError("version not found", 404)
        return loads(row["snapshot"], [])

    def _dup_checker(self, run_id: int | None):
        """Only runs from the same source count: an evaluation never makes an upload a duplicate, nor the other way.
        Evaluation history rows (the earlier invoice a duplicate sample copies) count for evaluation runs."""
        row = self.db.one("SELECT source FROM runs WHERE id=?", (run_id,)) if run_id is not None else None
        source = (row or {}).get("source") or "upload"
        sources = ("evaluation", "history") if source == "evaluation" else (source, source)

        def check(vat: str, number: str) -> bool:
            # compared after normalising: Arabic-Indic digits, spaces, letter case
            want = (vat_key(vat), number_key(number))
            if not all(want):
                return False
            rows = self.db.all("SELECT fields, final_fields FROM runs WHERE (? IS NULL OR id < ?) AND source IN (?,?) AND status NOT IN "
                               "('rejected','rejected_human','failed','queued')", (run_id, run_id, *sources))
            for r in rows:
                f = loads(r["final_fields"]) or loads(r["fields"], {}) or {}
                if (vat_key(f.get("seller_vat")), number_key(f.get("invoice_number"))) == want:
                    return True
            return False
        return check

    def _ctx(self, run_id: int | None, confidence: float) -> Ctx:
        return Ctx(today=self._today(), confidence=confidence, is_duplicate=self._dup_checker(run_id),
                   vendors=self.vendor_book(), po_for=self.po_by_number)

    # ------------------------------------------------------- vendors and purchase orders
    def vendor_book(self) -> VendorBook:
        return VendorBook(self.db.all("SELECT * FROM vendors"), self.db.all("SELECT vendor_id, alias FROM vendor_aliases"))

    def list_vendors(self) -> list[dict]:
        rows = self.db.all("SELECT * FROM vendors ORDER BY COALESCE(name_en, name_ar)")
        links = {r["vendor_id"]: r["n"] for r in self.db.all("SELECT vendor_id, COUNT(*) n FROM vendor_aliases GROUP BY vendor_id")}
        return [dict(r, linked_names=links.get(r["id"], 0)) for r in rows]

    def save_vendor(self, data: dict, actor: str, vendor_id: int | None = None) -> dict:
        v, errors = clean_vendor(data)
        if errors:
            raise DeskError("; ".join(errors))
        if v["vat"]:
            same = self.db.one("SELECT id FROM vendors WHERE vat=? AND id IS NOT ?", (v["vat"], vendor_id))
            if same:
                raise DeskError(f"another vendor already has VAT number {v['vat']}")
        t = now()
        if vendor_id is None:
            cur = self.db.run("INSERT INTO vendors(name_en,name_ar,vat,iban,currency,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                              (v["name_en"], v["name_ar"], v["vat"], v["iban"], v["currency"], v["status"], t, t))
            vendor_id = cur.lastrowid
            self.audit(actor, "vendor.create", str(vendor_id), v["name_en"] or v["name_ar"])
        else:
            old = self.db.one("SELECT * FROM vendors WHERE id=?", (vendor_id,))
            if not old:
                raise DeskError("vendor not found", 404)
            self.db.run("UPDATE vendors SET name_en=?,name_ar=?,vat=?,iban=?,currency=?,status=?,updated_at=? WHERE id=?",
                        (v["name_en"], v["name_ar"], v["vat"], v["iban"], v["currency"], v["status"], t, vendor_id))
            changed = [k for k in ("name_en", "name_ar", "vat", "iban", "currency", "status") if old[k] != v[k]]
            self.audit(actor, "vendor.update", str(vendor_id), ", ".join(changed) or "no change")
        return self.db.one("SELECT * FROM vendors WHERE id=?", (vendor_id,))

    def delete_vendor(self, vendor_id: int, actor: str) -> None:
        old = self.db.one("SELECT * FROM vendors WHERE id=?", (vendor_id,))
        if not old:
            raise DeskError("vendor not found", 404)
        self.db.run("DELETE FROM vendor_aliases WHERE vendor_id=?", (vendor_id,))
        self.db.run("UPDATE purchase_orders SET vendor_id=NULL WHERE vendor_id=?", (vendor_id,))
        self.db.run("DELETE FROM vendors WHERE id=?", (vendor_id,))
        self.audit(actor, "vendor.delete", str(vendor_id), old["name_en"] or old["name_ar"])

    def import_vendors(self, text: str, actor: str) -> dict:
        """Add or update vendors from CSV (name_en, name_ar, vat_number, iban, currency, status). A row with the VAT
        number of an existing vendor updates it; otherwise one with the same English name does; otherwise it is added."""
        added = updated = 0
        errors = []
        for n, row in enumerate(read_csv(text), 2):
            v, problems = clean_vendor(row)
            if problems:
                errors.append(dict(row=n, message="; ".join(problems)))
                continue
            old = (self.db.one("SELECT id FROM vendors WHERE vat=?", (v["vat"],)) if v["vat"] else None) or \
                (self.db.one("SELECT id FROM vendors WHERE name_en=?", (v["name_en"],)) if v["name_en"] else None)
            try:
                self.save_vendor(v, actor, old["id"] if old else None)
            except DeskError as exc:
                errors.append(dict(row=n, message=str(exc)))
                continue
            updated += bool(old)
            added += not old
        self.audit(actor, "vendor.import", "", f"{added} added, {updated} updated, {len(errors)} rows with errors")
        return dict(added=added, updated=updated, errors=errors[:50], error_count=len(errors))

    def list_pos(self) -> list[dict]:
        return self.db.all("SELECT * FROM purchase_orders ORDER BY po_number")

    def po_by_number(self, number: str) -> dict | None:
        return self.db.one("SELECT * FROM purchase_orders WHERE po_number=? COLLATE NOCASE", ((number or "").strip(),))

    def import_pos(self, text: str, actor: str) -> dict:
        """Add or update purchase orders from CSV (po_number, vendor, amount, currency, status), keyed by PO number.
        The vendor column is matched to the vendor master by name or VAT number, the same way invoices are."""
        book = self.vendor_book()
        added = updated = 0
        errors = []
        for n, row in enumerate(read_csv(text), 2):
            po, problems = clean_po(row)
            if problems:
                errors.append(dict(row=n, message="; ".join(problems)))
                continue
            who = po["vendor_name"] or ""
            m = book.match({"seller_name": who, "seller_vat": who if re.fullmatch(r"\s*3\d{13}3\s*", who) else None}) if book and who else None
            vendor = m["vendor"] if m else None
            old = self.po_by_number(po["po_number"])
            if old:
                self.db.run("UPDATE purchase_orders SET vendor_id=?,vendor_name=?,amount=?,currency=?,status=? WHERE id=?",
                            (vendor["id"] if vendor else None, po["vendor_name"], po["amount"], po["currency"], po["status"], old["id"]))
                updated += 1
            else:
                self.db.run("INSERT INTO purchase_orders(po_number,vendor_id,vendor_name,amount,currency,status,created_at) VALUES(?,?,?,?,?,?,?)",
                            (po["po_number"], vendor["id"] if vendor else None, po["vendor_name"], po["amount"], po["currency"], po["status"], now()))
                added += 1
        self.audit(actor, "po.import", "", f"{added} added, {updated} updated, {len(errors)} rows with errors")
        return dict(added=added, updated=updated, errors=errors[:50], error_count=len(errors))

    def delete_po(self, po_id: int, actor: str) -> None:
        old = self.db.one("SELECT * FROM purchase_orders WHERE id=?", (po_id,))
        if not old:
            raise DeskError("purchase order not found", 404)
        self.db.run("DELETE FROM purchase_orders WHERE id=?", (po_id,))
        self.audit(actor, "po.delete", str(po_id), old["po_number"])

    def link_vendor(self, rid: int, vendor_id: int, actor: str) -> dict:
        """Remember the run's seller name as a name of this vendor, then check the run again with that knowledge."""
        r = self.db.one("SELECT * FROM runs WHERE id=?", (rid,))
        if not r:
            raise DeskError("run not found", 404)
        vendor = self.db.one("SELECT * FROM vendors WHERE id=?", (vendor_id,))
        if not vendor:
            raise DeskError("vendor not found", 404)
        fields = self._current_fields(r) or {}
        name = (fields.get("seller_name") or "").strip()
        key = name_key(name)
        if not key:
            raise DeskError("this invoice has no seller name to link")
        self.db.run("INSERT INTO vendor_aliases(vendor_id,alias,key,created_by,created_at) VALUES(?,?,?,?,?) "
                    "ON CONFLICT(key) DO UPDATE SET vendor_id=excluded.vendor_id, alias=excluded.alias, created_by=excluded.created_by",
                    (vendor_id, name[:150], key, actor, now()))
        self.audit(actor, "vendor.link", str(rid), f'"{name}" is {vendor["name_en"] or vendor["name_ar"]}')
        if r["status"] == "needs_review":  # the decision stays with the reviewer; only the checks are refreshed
            conf = (loads(r["extraction"], {}) or {}).get("confidence", 1.0)
            results = run_rules(self.rules(), fields, self._ctx(rid, 1.0 if r["edited"] else conf))
            self.db.run("UPDATE runs SET results=?, updated_at=? WHERE id=?", (dumps(results), now(), rid))
        return self.get_run(rid)

    def _seed_vendor_data(self) -> None:
        """The demo vendors and purchase orders that the sample invoices refer to."""
        for name, fn in (("vendors.csv", self.import_vendors), ("purchase_orders.csv", self.import_pos)):
            path = SAMPLES_DIR / name
            if path.exists():
                self._seeding = True
                try:
                    fn(path.read_text(encoding="utf-8"), "system")
                finally:
                    self._seeding = False

    def simulate(self, candidate: list[dict] | None = None, limit: int = 300, rule: dict | None = None) -> dict:
        """Dry run: what would change if these rules had been in force for past runs? Nothing is written."""
        current = self.rules()
        if candidate is None:
            if rule is None:
                raise DeskError("send a rule or a full rule list")
            r = self._clean_rule(rule)
            candidate = [r if x["key"] == r["key"] else x for x in current]
            if r["key"] not in {x["key"] for x in current}:
                candidate = current + [r]
        else:
            candidate = [self._clean_rule(x) for x in candidate]
        rows = self.db.all("SELECT id,filename,fields,final_fields,extraction FROM runs WHERE fields IS NOT NULL "
                           "ORDER BY id DESC LIMIT ?", (limit,))
        changed, same = [], 0
        for r in rows:
            f = loads(r["final_fields"]) or loads(r["fields"], {})
            conf = (loads(r["extraction"], {}) or {}).get("confidence", 1.0)
            ctx = self._ctx(r["id"], conf)
            before, after = decide(run_rules(current, f, ctx)), decide(run_rules(candidate, f, ctx))
            if before != after:
                changed.append(dict(id=r["id"], filename=r["filename"], before=before, after=after))
            else:
                same += 1
        return dict(checked=len(rows), unchanged=same, changed=changed[:100], changed_count=len(changed),
                    shift=dict(Counter(f"{c['before']} -> {c['after']}" for c in changed)))

    # ----------------------------------------------------------------- intake
    def submit(self, filename: str, blob: bytes, content_type: str | None, actor: str, mode: str | None = None,
               llm: dict | None = None, source: str = "upload", defer: bool = False) -> int:
        """defer: store the run as queued and leave processing to the caller (the demo loader does, in date order)."""
        filename = clean_filename(filename)
        ctype = guess_type(filename, content_type)
        if ctype not in ALLOWED_TYPES:
            raise DeskError(f"unsupported file type {ctype}", 415)
        if not blob:
            raise DeskError("empty file")
        if len(blob) > MAX_BYTES:
            raise DeskError("file is larger than 5 MB", 413)
        if not content_matches(ctype, blob):
            raise DeskError(f"{filename} does not look like {_KIND.get(ctype, ctype)}", 415)
        if ctype == XML:
            try:
                check_safe(blob)
            except XmlError as exc:
                raise DeskError(f"{filename}: {exc}", 415) from None
        mode = mode or self.settings()["default_mode"]
        if mode not in ("rules", "ai"):
            raise DeskError("mode must be rules or ai")
        if mode == "ai":
            if not (llm and llm.get("provider")):
                raise DeskError("choose an AI provider and add its key in Settings")
            if self.extractor_factory == self._default_factory:
                self._default_factory("ai", llm)  # fails early with a readable message
        t = now()
        cur = self.db.run("INSERT INTO runs(filename,content_type,blob,source,size,status,mode,created_at,updated_at,submitted_by,trace)"
                          " VALUES(?,?,?,?,?,?,?,?,?,?,?)", (filename, ctype, blob, source, len(blob), "queued", mode, t, t, actor, "[]"))
        rid = cur.lastrowid
        self.audit(actor, "run.submit", str(rid), f"{filename} ({mode})")
        if defer:
            return rid
        if self.sync:
            self.process(rid, llm)
        else:
            self.pool.submit(self.process, rid, llm)
        return rid

    def _step(self, trace: list, name: str, t0: float, detail: str = "", ok: bool = True) -> None:
        trace.append(dict(step=name, ms=int((time.time() - t0) * 1000), ok=ok, detail=detail, at=now()))

    def process(self, rid: int, llm: dict | None = None) -> None:
        row = self.db.one("SELECT * FROM runs WHERE id=?", (rid,))
        if not row:
            return
        trace: list = [dict(step="ingest", ms=0, ok=True, detail=f"{row['filename']} · {row['size']} bytes · {row['content_type']}", at=row["created_at"])]
        self.db.run("UPDATE runs SET status='processing', updated_at=? WHERE id=?", (now(), rid))
        s = self.settings()
        try:
            t0 = time.time()
            ext = None
            notes: list = []
            try:
                # UBL XML is read directly whatever the reading mode: the fields are already structured
                extractor = UblExtractor() if row["content_type"] == XML else self.extractor_factory(row["mode"], llm)
                ext = extractor.extract(row["blob"], row["content_type"], row["filename"])
                self._step(trace, "extract", t0, f"{ext.extractor} · confidence {ext.confidence}")
            except NeedsVision as exc:
                ext = Extraction(empty_fields(), 0.0, {}, [f"Could not read automatically: {exc}. Switch to an AI model or key it in."], "rule-based")
                self._step(trace, "extract", t0, str(exc), ok=False)
            except (DeskError, XmlError):
                raise
            except Exception as exc:
                if row["mode"] != "ai":
                    raise
                self._step(trace, "extract", t0, f"AI call failed ({str(exc)[:140] or type(exc).__name__}); falling back to rule-based", ok=False)
                notes.append("The AI call failed, so the built-in reader was used instead")
                try:
                    ext = RuleBasedExtractor().extract(row["blob"], row["content_type"], row["filename"])
                except NeedsVision as nv:
                    ext = Extraction(empty_fields(), 0.0, {}, [f"Could not read automatically: {nv}"], "rule-based")
            ext.notes = list(ext.notes or []) + notes
            if not ext.fields.get("qr_payload") and (row["content_type"] in IMAGE_TYPES or row["content_type"] == "application/pdf"):
                tq = time.time()
                try:
                    found = find_in_file(row["blob"], row["content_type"])
                except Exception as exc:  # noqa: BLE001 - an unreadable image only means no QR was read
                    found = None
                    self._step(trace, "qr", tq, f"could not look for a QR code: {type(exc).__name__}", ok=False)
                else:
                    self._step(trace, "qr", tq, "QR code read from the image" if found else "no readable QR code found", ok=bool(found))
                if found:
                    ext.fields["qr_payload"] = found
            fields = {k: ext.fields.get(k) for k in FIELDS}
            t1 = time.time()
            results = run_rules(self.rules(), fields, self._ctx(rid, ext.confidence))
            decision = decide(results)
            fails = [x["name"] for x in results if x["status"] == "fail"]
            self._step(trace, "validate", t1, f"{len(results)} rules, {len(fails)} failed" + (f": {', '.join(fails)}" if fails else ""))
            if decision == "approved" and s["auto_approve"] == "false":
                decision = "needs_review"
                self._step(trace, "route", time.time(), "auto-approve is switched off, sent to review")
            else:
                self._step(trace, "route", time.time(), {"approved": "auto-approved", "needs_review": "sent to human review", "rejected": "rejected automatically"}[decision])
            meta = dict(confidence=ext.confidence, field_confidence=ext.field_confidence, notes=ext.notes, extractor=ext.extractor,
                        model=ext.model, tokens_in=ext.tokens_in, tokens_out=ext.tokens_out, latency_ms=ext.latency_ms)
            self.db.run("UPDATE runs SET status=?, fields=?, extraction=?, results=?, rules_version=?, trace=?, updated_at=?, "
                        "decided_at=? WHERE id=?",
                        (decision, dumps(fields), dumps(meta), dumps(results), self.rules_version(), dumps(trace), now(),
                         now() if decision != "needs_review" else None, rid))
            self.audit("system", "run.decision", str(rid), decision)
        except Exception as exc:
            self._step(trace, "error", time.time(), f"{type(exc).__name__}: {exc}"[:300], ok=False)
            self.db.run("UPDATE runs SET status='failed', error=?, trace=?, updated_at=?, decided_at=? WHERE id=?",
                        (friendly_error(exc), dumps(trace), now(), now(), rid))
            self.audit("system", "run.failed", str(rid), str(exc)[:200])

    # ------------------------------------------------------------------ reads
    @staticmethod
    def _current_fields(r: dict) -> dict | None:
        """The reviewer's corrected fields when there are any, otherwise what the reader extracted."""
        return loads(r["final_fields"]) or loads(r["fields"])

    def _run_view(self, r: dict, full: bool = False) -> dict:
        ex = loads(r["extraction"], {}) or {}
        out = dict(id=r["id"], filename=r["filename"], content_type=r["content_type"], size=r["size"], source=r["source"],
                   status=r["status"], mode=r["mode"], created_at=r["created_at"], updated_at=r["updated_at"],
                   decided_at=r["decided_at"], decision_by=r["decision_by"], submitted_by=r["submitted_by"],
                   edited=bool(r["edited"]), error=r["error"], rules_version=r["rules_version"],
                   confidence=ex.get("confidence"), extractor=ex.get("extractor"),
                   fields=self._current_fields(r))
        if out["fields"]:
            out["summary"] = {k: out["fields"].get(k) for k in ("invoice_number", "seller_name", "total", "currency")}
        if full:
            results = loads(r["results"], [])
            out.update(extracted=loads(r["fields"]), final_fields=loads(r["final_fields"]), extraction=ex, results=results,
                       trace=loads(r["trace"], []), decision_note=r["decision_note"])
        return out

    def get_run(self, rid: int) -> dict:
        r = self.db.one("SELECT * FROM runs WHERE id=?", (rid,))
        if not r:
            raise DeskError("run not found", 404)
        out = self._run_view(r, True)
        fields = out.get("fields") or {}
        book = self.vendor_book()
        if book and (fields.get("seller_name") or fields.get("seller_vat")):
            vm = book.match(fields)
            out["vendor_match"] = dict(vm, vendor={k: vm["vendor"][k] for k in ("id", "name_en", "name_ar", "vat", "iban", "currency", "status")}
                                       if vm["vendor"] else None)
        else:
            out["vendor_match"] = None
        po_rule = next((x for x in self.rules() if x["type"] == "po_amount" and x["enabled"]), None)
        params = (po_rule or {}).get("params") or {}
        number = (fields.get("po_number") or "").strip()
        out["po_match"] = po_match(fields, self.po_by_number(number) if number else None,
                                   (out["vendor_match"] or {}).get("vendor"), float(params.get("tolerance", 0.01)), params.get("field", "total"))
        out["timeline"] = self.timeline(r)
        return out

    _EDITED = re.compile(r"\s*\[edited: ([a-z_, ]+)\]$")

    def timeline(self, r: dict) -> list[dict]:
        """What happened to one invoice, oldest first, from its audit rows and its own fields.

        Each processing ends in a run.decision or run.failed audit row. Only the latest processing still has its trace,
        so only that one says which reader read it and which rules version checked it; an earlier one (before a
        "read again") shows its outcome alone."""
        rid = str(r["id"])
        rows = self.db.all("SELECT ts, actor, action, detail FROM audit WHERE target=? AND "
                           "(action IN ('run.decision', 'run.failed', 'run.reprocess', 'vendor.link', 'agent.propose') "
                           "OR action LIKE 'review.%') "
                           "ORDER BY ts, id", (rid,))
        trace = {s["step"]: s for s in loads(r["trace"], [])}
        ex = loads(r["extraction"], {}) or {}
        results = loads(r["results"], [])
        last = max((i for i, a in enumerate(rows) if a["action"] in ("run.decision", "run.failed")), default=-1)
        out: list[dict] = [dict(kind="received", at=r["created_at"], actor=r["submitted_by"], mode=r["mode"])]
        for i, a in enumerate(rows):
            if i == last:
                if "extract" in trace:
                    s = trace["extract"]
                    out.append(dict(kind="read", at=s["at"], ok=bool(s["ok"]), reader=ex.get("extractor"), model=ex.get("model"),
                                    confidence=ex.get("confidence"), fell_back="falling back" in (s.get("detail") or "")))
                if "validate" in trace:
                    # the run's results may have been worked out again since (after a review or a vendor link); the
                    # count at intake is in the trace step, the version is the one stored with the run
                    m = re.match(r"(\d+) rules, (\d+) failed", trace["validate"].get("detail") or "")
                    out.append(dict(kind="checked", at=trace["validate"]["at"], rules_version=r["rules_version"],
                                    checks=int(m[1]) if m else len(results), failed=int(m[2]) if m else None))
            act = a["action"]
            if act == "run.decision":
                route = (trace.get("route") or {}).get("detail", "") if i == last else ""
                out.append(dict(kind="routed", at=a["ts"], outcome=a["detail"], auto_approve_off=route.startswith("auto-approve is switched off")))
            elif act == "run.failed":
                out.append(dict(kind="failed", at=a["ts"]))
            elif act == "run.reprocess":
                out.append(dict(kind="reprocess", at=a["ts"], actor=a["actor"]))
            elif act == "vendor.link":
                out.append(dict(kind="vendor_link", at=a["ts"], actor=a["actor"]))
            elif act == "agent.propose":  # detail: "<recommendation>" or "<recommendation> (step limit)"
                out.append(dict(kind="copilot", at=a["ts"], actor=a["actor"], recommendation=(a["detail"] or "hold").split(" ")[0]))
            elif act in ("review.approve", "review.reject"):
                note, edited = a["detail"] or "", []
                m = self._EDITED.search(note)
                if m:
                    edited = [f for f in (x.strip() for x in m[1].split(",")) if f in FIELDS]
                    note = note[:m.start()]
                out.append(dict(kind="reviewed", at=a["ts"], actor=a["actor"], decision=act.split(".")[1], note=note.strip(), edited=edited))
        return out

    # ------------------------------------------------- copilot reads (read-only) and proposals
    def _earlier(self, rid: int) -> list[dict]:
        """Runs received before this one from the same kind of source (uploads, or an evaluation with its history),
        finished reading, newest first. What a reviewer could have looked up when this invoice arrived."""
        row = self.db.one("SELECT source FROM runs WHERE id=?", (rid,))
        if not row:
            raise DeskError("run not found", 404)
        sources = ("evaluation", "history") if row["source"] == "evaluation" else (row["source"], row["source"])
        return self.db.all("SELECT id, filename, status, created_at, fields, final_fields FROM runs WHERE id < ? AND source IN (?,?) "
                           "AND status NOT IN ('queued','processing') ORDER BY id DESC", (rid, *sources))

    @staticmethod
    def _brief(r: dict) -> dict:
        f = Desk._current_fields(r) or {}
        return dict(id=r["id"], status=r["status"], created_at=r["created_at"], invoice_number=f.get("invoice_number"),
                    total=f.get("total"), currency=f.get("currency"), iban=f.get("iban"))

    @staticmethod
    def _vendor_brief(v: dict) -> dict:
        return {k: v.get(k) for k in ("id", "name_en", "name_ar", "vat", "iban", "currency", "status")}

    def find_vendor(self, query: str) -> dict:
        """The vendor master entry for a seller name or VAT number, with the reason, as the intake checks see it."""
        q = (query or "").strip()[:150]
        book = self.vendor_book()
        if not book:
            return dict(vendor=None, why="The vendor master is empty.", suggestions=[])
        m = book.match({"seller_name": q, "seller_vat": q if vat_key(q) else None})
        return dict(vendor=self._vendor_brief(m["vendor"]) if m["vendor"] else None, score=round(m["score"], 3),
                    matched_on=m["matched_on"], why=m["why"], suggestions=m["suggestions"])

    def vendor_history(self, vendor_id: int, before_run: int, limit: int = 12) -> dict:
        """Earlier invoices that match this vendor: counts by outcome, the usual SAR total and the latest few."""
        v = self.db.one("SELECT * FROM vendors WHERE id=?", (vendor_id,))
        if not v:
            raise DeskError("vendor not found", 404)
        book = self.vendor_book()
        mine = []
        for r in self._earlier(before_run):
            f = self._current_fields(r) or {}
            if (f.get("seller_name") or f.get("seller_vat")) and (book.match(f)["vendor"] or {}).get("id") == vendor_id:
                mine.append(r)
        c = Counter(self._VALUE.get(r["status"], "other") for r in mine)
        sar = sorted(x for x in (self._sar(r) for r in mine if r["status"] in ("approved", "approved_human")) if x is not None)
        return dict(vendor=self._vendor_brief(v), count=len(mine), approved=c["approved"], rejected=c["rejected"],
                    waiting=c["waiting"], typical_total_sar=sar[len(sar) // 2] if sar else None,
                    largest_total_sar=sar[-1] if sar else None, latest=[self._brief(r) for r in mine[:limit]])

    def iban_history(self, vendor_id: int, before_run: int) -> dict:
        """The vendor master's IBAN and the IBANs printed on this vendor's earlier invoices, most used first."""
        h = self.vendor_history(vendor_id, before_run, limit=10_000)
        used: dict[str, dict] = {}
        for b in h["latest"]:  # newest first
            key = re.sub(r"\s+", "", (b["iban"] or "")).upper()
            if key:
                u = used.setdefault(key, dict(iban=key, count=0, latest_run=b["id"]))
                u["count"] += 1
        master = re.sub(r"\s+", "", h["vendor"]["iban"] or "").upper() or None
        return dict(vendor_id=vendor_id, master_iban=master, invoices=h["count"],
                    with_iban=sum(u["count"] for u in used.values()),
                    used=sorted(used.values(), key=lambda u: (-u["count"], u["iban"])))

    def similar_invoices(self, rid: int, limit: int = 10) -> list[dict]:
        """Earlier runs from the same seller (VAT number, or name when there is none) with the same invoice number or
        the same total. The duplicate rule only catches the first, and only once a run is not rejected."""
        r = self.db.one("SELECT * FROM runs WHERE id=?", (rid,))
        if not r:
            raise DeskError("run not found", 404)
        f = self._current_fields(r) or {}
        vat, name, number = vat_key(f.get("seller_vat")), name_key(f.get("seller_name")), number_key(f.get("invoice_number"))
        total = to_number(f.get("total"))
        if not (vat or name):
            return []
        out = []
        for e in self._earlier(rid):
            g = self._current_fields(e) or {}
            same_seller = vat_key(g.get("seller_vat")) == vat if vat else name_key(g.get("seller_name")) == name
            if not same_seller:
                continue
            why = []
            if number and number_key(g.get("invoice_number")) == number:
                why.append("same_number")
            t = to_number(g.get("total"))
            if total is not None and t is not None and abs(t - total) < 0.005:
                why.append("same_total")
            if why:
                out.append(dict(self._brief(e), why=why))
        return out[:limit]

    def agent_today(self) -> date:
        """Today for the copilot's prompt: the server clock in Saudi time (UTC+3, no daylight saving). A desk made with a
        fixed date (tests, the evaluation) keeps it. The checks themselves use _today(), so dates are judged by code."""
        return self.today or datetime.now(timezone(timedelta(hours=3))).date()

    def check_fields(self, rid: int, fields: dict | None = None, confidence: float | None = None) -> dict:
        """Run the full current rule set on these fields for this run and say what passed and what failed. Nothing is
        written. fields replace the run's current ones key by key (a re-read, say); confidence defaults to the run's own."""
        r = self.db.one("SELECT * FROM runs WHERE id=?", (rid,))
        if not r:
            raise DeskError("run not found", 404)
        f = empty_fields()
        f.update(self._current_fields(r) or {})
        f.update({k: v for k, v in (fields or {}).items() if k in FIELDS})
        if confidence is None:
            confidence = (loads(r["extraction"], {}) or {}).get("confidence", 1.0)
        rules = self.rules()
        types = {x["key"]: x["type"] for x in rules}
        results = run_rules(rules, f, self._ctx(rid, confidence))
        checks = [dict(key=x["key"], name=x["name"], type=types.get(x["key"]), severity=x["severity"], status=x["status"],
                       detail=x["detail"], risk=x.get("risk")) for x in results]
        return dict(checks=checks, failed=[c["key"] for c in checks if c["status"] == "fail" and c["severity"] != "info"],
                    passed=sum(c["status"] == "pass" for c in checks), today=self._today().isoformat())

    def save_proposal(self, rid: int, p: dict) -> dict:
        """Store what the copilot suggests. A proposal is advice: the run's status is never touched here."""
        cur = self.db.run("INSERT INTO proposals(run_id,mode,model,recommendation,summary,findings,evidence,steps,finished,tokens_in,"
                          "tokens_out,requested_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          # reasons and context share the findings column (as one object); evidence is no longer used
                          (rid, p["mode"], p.get("model"), p["recommendation"], dumps(p.get("summary")),
                           dumps(dict(reasons=p.get("reasons") or [], context=p.get("context") or [])),
                           "[]", dumps(p.get("steps") or []), 1 if p.get("finished", True) else 0,
                           p.get("tokens_in", 0), p.get("tokens_out", 0), p.get("requested_by"), now()))
        return self.proposals(rid)[0] if cur.lastrowid else {}

    def proposals(self, rid: int, limit: int = 5) -> list[dict]:
        rows = self.db.all("SELECT * FROM proposals WHERE run_id=? ORDER BY id DESC LIMIT ?", (rid, limit))
        out = []
        for r in rows:
            body = loads(r["findings"], {})
            if isinstance(body, list):  # an older proposal: findings with an effect; the facts that only informed are context
                body = dict(reasons=[f for f in body if f.get("effect") != "info"], context=[f for f in body if f.get("effect") == "info"])
            out.append({k: v for k, v in r.items() if k not in ("findings", "evidence")} | dict(
                summary=loads(r["summary"]), reasons=body.get("reasons", []), context=body.get("context", []),
                steps=loads(r["steps"], []), finished=bool(r["finished"])))
        return out

    def get_blob(self, rid: int) -> tuple[bytes, str, str]:
        r = self.db.one("SELECT blob,content_type,filename FROM runs WHERE id=?", (rid,))
        if not r:
            raise DeskError("run not found", 404)
        return r["blob"], r["content_type"], r["filename"]

    def invoice_view(self, rid: int) -> dict:
        """The UBL invoice of an XML run, laid out for reading. 404 for other file types, 422 if the XML cannot be read."""
        blob, ctype, _ = self.get_blob(rid)
        if ctype != "application/xml":
            raise DeskError("this run is not an XML invoice", 404)
        try:
            return ubl.view(blob)
        except ubl.XmlError as exc:
            raise DeskError(str(exc), 422) from None

    def list_runs(self, status: str | None = None, q: str | None = None, limit: int = 50, offset: int = 0,
                  source: str | None = None) -> dict:
        where, args = [], []
        if source in SOURCES:
            where.append("source=?")
            args.append(source)
        if status:
            where.append("status IN (%s)" % ",".join("?" * len(status.split(","))))
            args += status.split(",")
        if q:
            where.append("(filename LIKE ? OR fields LIKE ?)")
            args += [f"%{q}%", f"%{q}%"]
        w = ("WHERE " + " AND ".join(where)) if where else ""
        total = self.db.one(f"SELECT COUNT(*) n FROM runs {w}", args)["n"]
        cols = "id,filename,content_type,size,source,status,mode,created_at,updated_at,decided_at,decision_by,submitted_by,edited,error,rules_version,extraction,fields,final_fields"
        rows = self.db.all(f"SELECT {cols} FROM runs {w} ORDER BY id DESC LIMIT ? OFFSET ?", args + [min(limit, 200), offset])
        return dict(total=total, items=[self._run_view(r) for r in rows])

    def next_review(self, after_id: int | None = None) -> dict | None:
        r = self.db.one("SELECT * FROM runs WHERE status='needs_review' AND source='upload' ORDER BY id LIMIT 1")
        return self._run_view(r, True) if r else None

    def review_queue(self) -> list[dict]:
        """Every run waiting for a person, oldest first, without blobs or traces: enough to draw a list."""
        rows = self.db.all("SELECT id,filename,created_at,fields,final_fields,results FROM runs "
                           "WHERE status='needs_review' AND source='upload' ORDER BY id")
        out = []
        for r in rows:
            f = self._current_fields(r) or {}
            results = loads(r["results"], [])
            out.append(dict(id=r["id"], filename=r["filename"], created_at=r["created_at"], seller=f.get("seller_name"),
                            invoice_number=f.get("invoice_number"), total=f.get("total"), currency=f.get("currency"),
                            failed_checks=sum(1 for x in results if x["status"] == "fail" and x["severity"] == "review"),
                            high_risk=any(x["status"] == "fail" and x.get("risk") == "high" for x in results)))
        return out

    # ----------------------------------------------------------------- review
    def review(self, rid: int, decision: str, actor: str, edits: dict | None = None, note: str = "") -> dict:
        r = self.db.one("SELECT * FROM runs WHERE id=?", (rid,))
        if not r:
            raise DeskError("run not found", 404)
        if r["source"] == "evaluation":
            raise DeskError("evaluation runs are scored against the answer key, not reviewed", 409)
        if r["status"] != "needs_review":
            raise DeskError(f"run is {r['status']}, only runs waiting for review can be decided", 409)
        if decision not in ("approve", "reject"):
            raise DeskError("decision must be approve or reject")
        if decision == "reject" and not (note or "").strip():
            raise DeskError("add a note explaining the rejection")
        if len(note or "") > MAX_REVIEW_NOTE:
            raise DeskError(f"the note can be at most {MAX_REVIEW_NOTE} characters")
        fields = loads(r["fields"], empty_fields())
        final = dict(fields)
        changed = []
        for k, v in (edits or {}).items():
            if k not in FIELDS:
                raise DeskError(f"unknown field {k}")
            if k in NUMERIC:
                v = to_number(v) if v not in (None, "") else None
                if v is None and edits[k] not in (None, ""):
                    raise DeskError(f"{k} must be a number")
            elif k in ("issue_date", "due_date") and v:
                v = parse_date(v)
                if not v:
                    raise DeskError(f"{k} is not a valid date")
            elif k != "line_items":
                v = (str(v).strip() or None) if v is not None else None
            if final.get(k) != v:
                changed.append(k)
                final[k] = v
        conf = (loads(r["extraction"], {}) or {}).get("confidence", 1.0)
        results = run_rules(self.rules(), final, self._ctx(rid, 1.0 if changed else conf))
        trace = loads(r["trace"], [])
        trace.append(dict(step="human review", ms=0, ok=True, at=now(),
                          detail=f"{actor} chose {decision}" + (f", corrected {', '.join(changed)}" if changed else "")))
        status = "approved_human" if decision == "approve" else "rejected_human"
        self.db.run("UPDATE runs SET status=?, final_fields=?, results=?, edited=?, decision_by=?, decision_note=?, decided_at=?, "
                    "updated_at=?, trace=? WHERE id=?",
                    (status, dumps(final), dumps(results), 1 if changed else 0, actor, note, now(), now(), dumps(trace), rid))
        self.audit(actor, f"review.{decision}", str(rid), (note or "") + (f" [edited: {', '.join(changed)}]" if changed else ""))
        return self.get_run(rid)

    def reprocess(self, rid: int, actor: str, llm: dict | None = None) -> None:
        r = self.db.one("SELECT status, mode FROM runs WHERE id=?", (rid,))
        if not r:
            raise DeskError("run not found", 404)
        if r["status"] in ("processing", "queued"):
            raise DeskError("run is still processing", 409)
        if r["mode"] == "ai" and not (llm and llm.get("provider")):
            raise DeskError("choose an AI provider and add its key in Settings")
        self.db.run("UPDATE runs SET status='queued', final_fields=NULL, edited=0, decision_by=NULL, decision_note=NULL WHERE id=?", (rid,))
        self.audit(actor, "run.reprocess", str(rid))
        if self.sync:
            self.process(rid, llm)
        else:
            self.pool.submit(self.process, rid, llm)

    # ------------------------------------------------------------- demo load
    def load_demo(self, actor: str, plan: list[dict], read) -> list[int]:
        """Load sample invoices with a history. plan: items in date order (see samples.demo_plan), read(file) -> bytes.
        Every run is stored first, then one job reads them in order through the built-in reader, takes the demo
        reviewer's decision where a history invoice lands in review, and moves the run's timestamps to its planned
        date. In date order the duplicate check sees the same invoices it would have seen on those days.
        A fresh load (no uploads yet) checks them with the default rules, so the rules go back to version 1 first."""
        if not self.db.one("SELECT id FROM runs WHERE source='upload' LIMIT 1"):
            self._restore_default_rules()
        ids = [self.submit(p["file"], read(p["file"]), None, actor, "rules", None, source="upload", defer=True) for p in plan]

        def work() -> None:
            for rid, p in zip(ids, plan):
                self.process(rid)  # handles its own errors: a run that cannot be read ends as failed
                d = p.get("decide")
                after = None
                row = self.db.one("SELECT status FROM runs WHERE id=?", (rid,))
                if not row:  # the demo was reset while loading
                    continue
                try:
                    if d and row["status"] == "needs_review":
                        decision, note = d["decision"], d.get("note", "")
                        f = self.get_run(rid)["fields"] or {}
                        if decision == "approve" and not (f.get("seller_name") and f.get("total") is not None):
                            decision, note = "reject", d.get("unreadable_note") or "Could not be read"
                        self.review(rid, decision, d["actor"], note=note)
                        after = d["after"]
                    self._backdate(rid, p["at"], after)
                except DeskError:  # the run was reset or changed meanwhile; leave it as it is and carry on
                    continue
        if self.sync:
            work()
        else:
            self.pool.submit(work)
        return ids

    def _backdate(self, rid: int, at: datetime, decided_after: timedelta | None = None) -> None:
        """Move a run, its trace and its audit rows so it was received at `at`. A person's decision is put
        `decided_after` later (never past the present); an automatic one keeps its few seconds."""
        r = self.db.one("SELECT created_at, decided_at, trace FROM runs WHERE id=?", (rid,))
        shift = at - datetime.fromisoformat(r["created_at"])

        def moved(stamp: str | None) -> str | None:
            return (datetime.fromisoformat(stamp) + shift).isoformat(timespec="seconds") if stamp else stamp
        human = None
        if decided_after is not None:
            human = min(at + decided_after, datetime.now(timezone.utc)).isoformat(timespec="seconds")
        trace = loads(r["trace"], []) or []
        for step in trace:
            step["at"] = human if human and step.get("step") == "human review" else moved(step.get("at"))
        decided = human or moved(r["decided_at"])
        self.db.run("UPDATE runs SET created_at=?, updated_at=?, decided_at=?, trace=? WHERE id=?",
                    (at.isoformat(timespec="seconds"), decided or at.isoformat(timespec="seconds"), decided, dumps(trace), rid))
        for a in self.db.all("SELECT id, ts, action FROM audit WHERE target=? AND (action LIKE 'run.%' OR action LIKE 'review.%')",
                             (str(rid),)):
            ts = human if human and a["action"].startswith("review.") else moved(a["ts"])
            self.db.run("UPDATE audit SET ts=? WHERE id=?", (ts, a["id"]))

    # ------------------------------------------------------------------ stats
    def clear_evaluation_runs(self) -> int:
        """Remove the runs kept from earlier evaluations; uploads are never touched."""
        return self.db.run("DELETE FROM runs WHERE source='evaluation'").rowcount

    def record_evaluation_runs(self, runs: list[dict]) -> int:
        """Keep the runs an evaluation made on its scratch database, tagged evaluation, so they can be opened later.
        They are scored against the answer key and never wait in the review queue."""
        cols = ("filename", "content_type", "blob", "size", "status", "mode", "fields", "extraction", "results", "rules_version",
                "error", "created_at", "updated_at", "decided_at", "submitted_by", "trace")
        for r in runs:
            self.db.run(f"INSERT INTO runs(source,{','.join(cols)}) VALUES('evaluation',{','.join('?' * len(cols))})",
                        tuple(r.get(c) for c in cols))
        return len(runs)

    def stats(self, source: str | None = None, days: int | None = None) -> dict:
        """source: upload or evaluation; anything else counts every run. The review queue is always uploads only.
        days: also return a `period` block for the last `days` days against the same length before (7, 30 or 90)."""
        if days is not None and days not in self.PERIODS:
            raise DeskError(f"days must be one of {', '.join(map(str, self.PERIODS))}")
        period_days = days
        where = "WHERE source=?" if source in SOURCES else ""
        rows = self.db.all(f"SELECT id,status,mode,created_at,decided_at,results,extraction,edited,fields,final_fields FROM runs {where}",
                           (source,) if where else ())
        by_status = Counter(r["status"] for r in rows)
        s = self.settings()
        tin = tout = 0
        latencies, ttr = [], []
        failing: Counter = Counter()
        reasons: Counter = Counter()
        days = Counter()
        for r in rows:
            ex = loads(r["extraction"], {}) or {}
            tin += ex.get("tokens_in", 0) or 0
            tout += ex.get("tokens_out", 0) or 0
            if ex.get("latency_ms"):
                latencies.append(ex["latency_ms"])
            for x in loads(r["results"], []) or []:
                if x["status"] == "fail":
                    failing[x["name"]] += 1
                    if r["status"] == "rejected" and x["severity"] == "reject":
                        reasons[x["name"]] += 1
            if r["status"] == "rejected_human":
                reasons["Rejected by a reviewer"] += 1
            elif r["status"] == "failed":
                reasons["Could not be processed"] += 1
            days[r["created_at"][:10]] += 1
            if r["status"] in ("approved_human", "rejected_human") and r["decided_at"]:
                ttr.append((datetime.fromisoformat(r["decided_at"]) - datetime.fromisoformat(r["created_at"])).total_seconds())
        machine_done = sum(by_status[k] for k in ("approved", "rejected", "needs_review", "approved_human", "rejected_human"))
        end = self._today()
        series = [dict(day=(end - timedelta(days=i)).isoformat(), count=days.get((end - timedelta(days=i)).isoformat(), 0)) for i in range(13, -1, -1)]
        cost = None
        if s["price_in_per_mtok"] != "" and s["price_out_per_mtok"] != "":
            cost = round(tin / 1e6 * float(s["price_in_per_mtok"]) + tout / 1e6 * float(s["price_out_per_mtok"]), 4)
        return dict(total=len(rows), by_status={k: by_status.get(k, 0) for k in
                                                ("approved", "needs_review", "rejected", "approved_human", "rejected_human", "failed", "queued", "processing")},
                    review_queue=self.db.one("SELECT COUNT(*) n FROM runs WHERE status='needs_review' AND source='upload'")["n"],
                    source=source if source in SOURCES else "all",
                    uploads=self.db.one("SELECT COUNT(*) n FROM runs WHERE source='upload'")["n"],
                    auto_approve_rate=round(by_status["approved"] / machine_done, 3) if machine_done else None,
                    human_corrected=sum(1 for r in rows if r["edited"]),
                    avg_extract_ms=int(sum(latencies) / len(latencies)) if latencies else None,
                    avg_time_to_review_s=int(sum(ttr) / len(ttr)) if ttr else None,
                    tokens_in=tin, tokens_out=tout, cost=cost, ai_runs=sum(1 for r in rows if r["mode"] == "ai"),
                    top_failing=[dict(rule=k, count=v) for k, v in failing.most_common(6)],
                    top_rejections=[dict(reason=k, count=v) for k, v in reasons.most_common(6)], series=series,
                    rules_version=self.rules_version(), **({"period": self._period(rows, period_days)} if period_days else {}))

    PERIODS = (1, 7, 30, 90)  # 1 is "Today", drawn by the hour
    _OUTCOME = {"approved": "auto", "approved_human": "person", "needs_review": "review", "rejected": "rejected",
                "rejected_human": "rejected", "failed": "rejected"}
    _VALUE = {"approved": "approved", "approved_human": "approved", "needs_review": "waiting", "rejected": "rejected",
              "rejected_human": "rejected"}

    def _sar(self, r: dict) -> float | None:
        """The invoice total when it is in SAR, else None. Other currencies are counted, never converted."""
        f = self._current_fields(r) or {}
        total = f.get("total")
        if (f.get("currency") or "").strip().upper() != "SAR" or isinstance(total, bool) or not isinstance(total, (int, float)):
            return None
        return float(total)

    def _figures(self, rows: list[dict]) -> dict:
        c = Counter(r["status"] for r in rows)
        done = sum(c[k] for k in ("approved", "rejected", "needs_review", "approved_human", "rejected_human"))
        value = {"approved": 0.0, "waiting": 0.0, "rejected": 0.0}
        other = 0
        for r in rows:
            key = self._VALUE.get(r["status"])
            if not key:
                continue
            v = self._sar(r)
            if v is None:
                other += 1
            else:
                value[key] += v
        ttr = [(datetime.fromisoformat(r["decided_at"]) - datetime.fromisoformat(r["created_at"])).total_seconds()
               for r in rows if r["status"] in ("approved_human", "rejected_human") and r["decided_at"]]
        return dict(received=len(rows), approved=c["approved"], approved_human=c["approved_human"], waiting=c["needs_review"],
                    rejected=c["rejected"] + c["rejected_human"] + c["failed"],
                    auto_approve_rate=round(c["approved"] / done, 3) if done else None,
                    avg_time_to_review_s=int(sum(ttr) / len(ttr)) if ttr else None,
                    value={k: round(v, 2) for k, v in value.items()}, other_currency=other)

    @staticmethod
    def _fails(rows: list[dict]) -> Counter:
        out: Counter = Counter()
        for r in rows:
            for x in loads(r["results"], []) or []:
                if x["status"] == "fail":
                    out[x["name"]] += 1
        return out

    def _period(self, rows: list[dict], days: int) -> dict:
        """Figures for the last `days` days (by the day each invoice arrived, today included) and for the window of the
        same length before it, so the portal can show the change. Amounts are summed in SAR only."""
        end = self._today()
        start = end - timedelta(days=days - 1)
        before = start - timedelta(days=days)
        cur, prev = [], []
        for r in rows:
            d = date.fromisoformat(r["created_at"][:10])
            if d >= start:  # a run dated after "today" (a clock set back, a fixed test date) still counts as recent
                cur.append(r)
            elif before <= d < start:
                prev.append(r)
        # one point a day, or for Today one an hour (UTC, as stored; the portal shows local time)
        if days == 1:
            keys = [f"{end.isoformat()}T{h:02d}" for h in range(24)]
            label = lambda k: f"{k}:00:00+00:00"  # noqa: E731
            width = 13
        else:
            keys = [(start + timedelta(days=i)).isoformat() for i in range(days)]
            label = lambda k: k  # noqa: E731
            width = 10
        series = {k: dict(auto=0, person=0, review=0, rejected=0, value=0.0) for k in keys}
        for r in cur:
            b = series.get(r["created_at"][:width])
            if b is None:
                continue
            if r["status"] in self._OUTCOME:
                b[self._OUTCOME[r["status"]]] += 1
            b["value"] += self._sar(r) or 0.0
        now_f = self._fails(cur)
        reasons: Counter = Counter()
        for r in cur:
            if r["status"] == "rejected_human":
                reasons["Rejected by a reviewer"] += 1
            elif r["status"] == "failed":
                reasons["Could not be processed"] += 1
            elif r["status"] == "rejected":
                for x in loads(r["results"], []) or []:
                    if x["status"] == "fail" and x["severity"] == "reject":
                        reasons[x["name"]] += 1
        first, last = end.isoformat(), (end + timedelta(days=7)).isoformat()
        due = [r for r in rows if r["status"] in ("approved", "approved_human")
               and first <= (parse_date((self._current_fields(r) or {}).get("due_date") or "") or "") <= last]
        due_sar = [self._sar(r) for r in due]
        queue = self.review_queue()  # oldest first
        return dict(days=days, start=start.isoformat(), end=first, current=self._figures(cur), previous=self._figures(prev),
                    series=[dict(day=label(k), **{**v, "value": round(v["value"], 2)}) for k, v in series.items()],
                    top_failing=[dict(rule=k, count=v) for k, v in now_f.most_common(6)],
                    top_rejections=[dict(reason=k, count=v) for k, v in reasons.most_common(6)],
                    waiting=queue[:5], waiting_count=len(queue),
                    waiting_value=round(sum(v for v in (self._sar_q(q) for q in queue) if v is not None), 2),
                    high_risk=sum(1 for q in queue if q["high_risk"]),
                    due_soon=dict(count=len(due), value=round(sum(v for v in due_sar if v is not None), 2),
                                  other_currency=sum(1 for v in due_sar if v is None)))

    @staticmethod
    def _sar_q(q: dict) -> float | None:
        t = q.get("total")
        return float(t) if (q.get("currency") or "").upper() == "SAR" and isinstance(t, (int, float)) and not isinstance(t, bool) else None

    # Audit actions a person did, or would want to hear about: the dashboard's activity feed.
    ACTIVITY = ("review.approve", "review.reject", "run.reprocess", "vendor.link", "vendor.create", "vendor.update",
                "vendor.delete", "vendor.import", "po.import", "po.delete", "rule.update", "rule.delete", "rule.reorder",
                "rule.rollback", "settings.update", "demo.samples", "demo.reset")

    def activity(self, limit: int = 8) -> list[dict]:
        """Recent audit rows from ACTIVITY, newest first. Review rows carry the invoice's seller, number and total."""
        rows = self.db.all(f"SELECT * FROM audit WHERE action IN ({','.join('?' * len(self.ACTIVITY))}) "
                           "ORDER BY ts DESC, id DESC LIMIT ?", (*self.ACTIVITY, max(1, min(limit, 50))))
        for a in rows:
            a["run"] = None
            if a["action"].startswith("review.") and a["target"].isdigit():
                r = self.db.one("SELECT filename, fields, final_fields FROM runs WHERE id=?", (int(a["target"]),))
                if r:
                    f = self._current_fields(r) or {}
                    a["run"] = dict({k: f.get(k) for k in ("seller_name", "invoice_number", "total", "currency")}, filename=r["filename"])
        return rows

    def audit_log(self, limit: int = 200, actor: str | None = None, action: str | None = None) -> list[dict]:
        where, args = [], []
        if actor:
            where.append("actor=?")
            args.append(actor)
        if action:
            where.append("action LIKE ?")
            args.append(action + "%")
        w = ("WHERE " + " AND ".join(where)) if where else ""
        return self.db.all(f"SELECT * FROM audit {w} ORDER BY ts DESC, id DESC LIMIT ?", args + [min(limit, 1000)])

    # ----------------------------------------------------------------- export
    def export_csv(self) -> str:
        buf = io.StringIO()
        w = csv.writer(buf)
        cols = ["id", "filename", "status", "invoice_number", "issue_date", "seller_name", "seller_vat", "buyer_name", "currency",
                "subtotal", "vat_amount", "total", "confidence", "decision_by", "created_at", "decided_at"]
        w.writerow(cols)
        for r in self.db.all("SELECT * FROM runs ORDER BY id"):
            if r["status"] not in ("approved", "approved_human"):
                continue
            f = loads(r["final_fields"]) or loads(r["fields"], {}) or {}
            ex = loads(r["extraction"], {}) or {}
            row = dict(id=r["id"], filename=r["filename"], status=r["status"], confidence=ex.get("confidence"),
                       decision_by=r["decision_by"] or "auto", created_at=r["created_at"], decided_at=r["decided_at"])
            w.writerow([row.get(c, f.get(c)) for c in cols])
        return buf.getvalue()

    # ------------------------------------------------------------------ reset
    def reset(self, actor: str, keep_rules: bool = False) -> None:
        with self.db.lock:
            self.db.conn.execute("DELETE FROM runs")
            self.db.conn.execute("DELETE FROM audit")
            self.db.conn.execute("DELETE FROM proposals")
            self.db.conn.commit()
        if not keep_rules:
            self._restore_default_rules()
        if self.seed_vendors:  # the demo's vendor master and POs go back to how they started
            for table in ("vendor_aliases", "purchase_orders", "vendors"):
                self.db.run(f"DELETE FROM {table}")
            self._seed_vendor_data()
        self.audit(actor, "demo.reset")

    def wait_idle(self, timeout: float = 30) -> None:
        t0 = time.time()
        while time.time() - t0 < timeout:
            if not self.db.one("SELECT id FROM runs WHERE status IN ('queued','processing') LIMIT 1"):
                return
            time.sleep(0.05)
