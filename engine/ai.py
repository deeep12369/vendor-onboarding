"""
ai.py — "the only file that talks to the AI".

Three jobs, all returning structured JSON that rules then check:
  1. extract_document  — tag a file (what document is it?) and read its fields
  2. match_names       — judge whether two names refer to the same party
  3. draft_message     — write the vendor email for fixable issues

Two modes:
  live     — calls Google Gemini over the internet (needs GEMINI_API_KEY)
  offline  — uses stored sample answers for the demo files, and simple
             heuristics for names/messages. A safety net for live demos.

Safeguards: temperature 0, JSON-only answers, validation of every answer,
retries with growing waits on rate limits (error 429), and a cache keyed by
each file's SHA-256 fingerprint so the same file never costs a second call.
"""
import hashlib
import json
import time
from pathlib import Path

from . import db
from .validators import clean_id, normalize_name

DATA = Path(__file__).resolve().parent.parent / "data"

DOC_TYPES = ["gst_certificate", "pan_card", "cancelled_cheque", "msme_certificate", "aadhaar", "other"]
DOC_LABELS = {"gst_certificate": "GST certificate", "pan_card": "PAN card",
              "cancelled_cheque": "Cancelled cheque", "msme_certificate": "MSME certificate",
              "aadhaar": "Aadhaar card", "other": "Unrecognised document", None: "Unidentified"}

# Which fields to read from each document type
DOC_FIELDS = {
    "gst_certificate": ["legal_name", "trade_name", "gstin", "state", "registration_date"],
    "pan_card": ["name", "pan"],
    "cancelled_cheque": ["account_holder_name", "account_number", "ifsc", "bank_name"],
    "msme_certificate": ["enterprise_name", "udyam_number"],
    "aadhaar": [],   # deliberately read nothing: not needed, and sensitive
    "other": [],
}
ID_FIELDS = {"gstin", "pan", "ifsc", "account_number", "udyam_number"}

DEFAULT_MODEL = "gemini-flash-latest"
FALLBACK_MODEL = "gemini-2.5-flash"

EXTRACT_PROMPT = """You are a document analyst for an Indian company's vendor onboarding team.
You are given ONE uploaded file. Do two things.

1. Identify the document type. Choose exactly one of:
   gst_certificate (GST registration certificate, Form GST REG-06),
   pan_card (Income Tax PAN card),
   cancelled_cheque (a bank cheque marked CANCELLED),
   msme_certificate (Udyam registration certificate),
   aadhaar (Aadhaar card),
   other (anything else).
   Give doc_type_confidence from 0 to 1.

2. Read these fields if the type has them:
   gst_certificate: legal_name, trade_name, gstin, state (principal place of business state), registration_date
   pan_card: name, pan
   cancelled_cheque: account_holder_name (the name printed on the cheque), account_number, ifsc, bank_name
   msme_certificate: enterprise_name, udyam_number
   aadhaar: read NO fields (do not return any personal data)
   other: no fields
   For each field return {"value": <text or null>, "confidence": <0 to 1>}.
   If a field is not present or you cannot read it clearly, return value null with low confidence.
   NEVER guess digits. Copy identifiers exactly as printed, without spaces.

3. quality_issue: null if the file is clear, otherwise a short phrase such as
   "blurred", "cropped", "low resolution", "partially hidden".

Reply with JSON only, in exactly this shape:
{"doc_type": "...", "doc_type_confidence": 0.0,
 "fields": {"<field>": {"value": "...", "confidence": 0.0}},
 "quality_issue": null, "notes": "<one short sentence on what you see>"}"""

NAME_PROMPT = """You compare names for an Indian vendor onboarding check.
For each pair, decide whether name_a and name_b refer to the same party.
Use the context (entity type, proprietor name) when given.
Choose exactly one match_class:
  exact            - same party; differences are only spelling, case, punctuation or abbreviations (Pvt/Private, Ltd/Limited)
  proprietor_match - a proprietorship whose name_b is the proprietor's personal name
  partial          - plausibly related but not clearly the same (shared words, different structure)
  different        - different parties
Give a one-line reason. Reply with JSON only:
{"results": [{"id": "...", "match_class": "...", "reason": "..."}]}

Pairs:
"""

MESSAGE_PROMPT = """Write a short, polite email from a procurement team to a vendor whose onboarding
is on hold. List each issue as a numbered point: what is wrong, and exactly what to send or correct.
Use only the issues given. Do not mention fraud, internal checks, scores or AI.
Do not invent deadlines or extra requirements. Sign off as "Vendor Onboarding Team".
Keep it under 180 words. Reply with JSON only: {"subject": "...", "body": "..."}

Vendor: {vendor}
Issues:
{issues}"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def fingerprint(file_bytes):
    return hashlib.sha256(file_bytes).hexdigest()


def mime_for(file_name):
    ext = file_name.lower().rsplit(".", 1)[-1]
    return {"pdf": "application/pdf", "jpg": "image/jpeg", "jpeg": "image/jpeg",
            "png": "image/png", "webp": "image/webp"}.get(ext, "application/octet-stream")


def _offline_answers():
    path = DATA / "offline_answers.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


class AIUnavailable(Exception):
    pass


def _call_gemini(cfg, contents):
    """One Gemini call with JSON output, temperature 0, and retries on rate limits."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=cfg["api_key"])
    config = types.GenerateContentConfig(temperature=0, response_mime_type="application/json")
    models = [cfg.get("model") or DEFAULT_MODEL]
    if FALLBACK_MODEL not in models:
        models.append(FALLBACK_MODEL)

    last_error = None
    for model in models:
        wait = 4
        for attempt in range(4):
            try:
                resp = client.models.generate_content(model=model, contents=contents, config=config)
                text = (resp.text or "").strip()
                if text.startswith("```"):
                    text = text.strip("`").removeprefix("json").strip()
                return json.loads(text), model
            except json.JSONDecodeError as exc:
                last_error = exc          # malformed answer: retry once more
                if attempt >= 1:
                    break
            except Exception as exc:
                last_error = exc
                msg = str(exc)
                if "429" in msg or "RESOURCE_EXHAUSTED" in msg or "503" in msg or "UNAVAILABLE" in msg:
                    if cfg.get("on_wait"):
                        cfg["on_wait"](f"Gemini is busy (rate limit); retrying in {wait}s")
                    time.sleep(wait)
                    wait *= 2             # exponential backoff: 4s, 8s, 16s
                    continue
                if "404" in msg or "NOT_FOUND" in msg:
                    break                 # model name not available: try the fallback model
                raise AIUnavailable(msg) from exc
    raise AIUnavailable(str(last_error))


def _validate_extraction(raw):
    """Force the AI's answer into the exact shape the rules expect."""
    doc_type = raw.get("doc_type")
    if doc_type not in DOC_TYPES:
        doc_type = "other"
    try:
        type_conf = float(raw.get("doc_type_confidence") or 0)
    except (TypeError, ValueError):
        type_conf = 0.0
    fields = {}
    raw_fields = raw.get("fields") or {}
    for name in DOC_FIELDS[doc_type]:
        item = raw_fields.get(name) or {}
        if not isinstance(item, dict):
            item = {"value": item, "confidence": 0.5}
        value = item.get("value")
        if isinstance(value, str):
            value = value.strip() or None
        if value is not None and name in ID_FIELDS:
            value = clean_id(value)
        try:
            conf = float(item.get("confidence") or 0)
        except (TypeError, ValueError):
            conf = 0.0
        fields[name] = {"value": value, "confidence": round(conf, 2)}
    return {"doc_type": doc_type, "doc_type_confidence": round(type_conf, 2), "fields": fields,
            "quality_issue": raw.get("quality_issue") or None, "notes": raw.get("notes") or ""}


# ---------------------------------------------------------------------------
# Job 1: tag and extract
# ---------------------------------------------------------------------------
def extract_document(file_bytes, file_name, cfg):
    sha = fingerprint(file_bytes)
    started = time.time()

    if cfg["mode"] == "offline":
        stored = _offline_answers().get(sha)
        if stored is None:
            return {"doc_type": None, "doc_type_confidence": 0.0, "fields": {}, "quality_issue": None,
                    "notes": "Offline mode has no stored answer for this file; switch to live AI to read it.",
                    "source": "offline (no stored answer)", "sha256": sha, "seconds": 0}
        out = _validate_extraction(stored)
        out.update(source="offline sample answer", sha256=sha, seconds=0)
        return out

    cache_key = f"extract:{sha}"
    cached = db.cache_get(cache_key)
    if cached:
        cached.update(source="cache (same file seen before)", sha256=sha, seconds=0)
        return cached

    from google.genai import types
    contents = [types.Part.from_bytes(data=file_bytes, mime_type=mime_for(file_name)), EXTRACT_PROMPT]
    try:
        raw, model = _call_gemini(cfg, contents)
    except AIUnavailable:
        stored = _offline_answers().get(sha)   # safety net for the demo files only, clearly labelled
        if stored is None:
            raise
        out = _validate_extraction(stored)
        out.update(source="offline sample answer (Gemini unavailable)", sha256=sha, seconds=0)
        return out
    out = _validate_extraction(raw)
    db.cache_put(cache_key, out)
    out.update(source=f"Gemini ({model})", sha256=sha, seconds=round(time.time() - started, 1))
    return out


# ---------------------------------------------------------------------------
# Job 2: name matching
# ---------------------------------------------------------------------------
_GENERIC = {"PRIVATE", "LIMITED", "LLP", "AND", "COMPANY", "INDIA", "ENTERPRISES", "TRADERS"}


def _heuristic_match(a, b):
    ta = set(normalize_name(a).split()) - _GENERIC
    tb = set(normalize_name(b).split()) - _GENERIC
    if not ta or not tb:
        return "partial", "Too few distinctive words to compare"
    overlap = len(ta & tb) / len(ta | tb)
    if overlap >= 0.5:
        return "partial", f"Share the words {', '.join(sorted(ta & tb))} but are not identical"
    if ta & tb:
        return "partial", f"Share only {', '.join(sorted(ta & tb))}"
    return "different", "No distinctive words in common"


def match_names(pairs, cfg):
    results = _match_names(pairs, cfg)
    for p in pairs:  # keep the names next to each verdict, for readable reasons and the audit trail
        if p["id"] in results:
            results[p["id"]].update(name_a=p["name_a"], name_b=p["name_b"])
    return results


def _match_names(pairs, cfg):
    """
    pairs: list of {"id", "name_a", "name_b", "context"}
    Cheap first: names identical after cleaning, or a proprietor's own name,
    are decided in code. Only the remaining pairs go to the AI, in ONE batched call.
    """
    results, to_ai = {}, []
    for p in pairs:
        na, nb = normalize_name(p["name_a"]), normalize_name(p["name_b"])
        ctx = p.get("context") or {}
        if na and na == nb:
            results[p["id"]] = {"match_class": "exact", "source": "code",
                                "reason": "Identical after cleaning (case, punctuation, Pvt/Ltd)"}
        elif ctx.get("entity_type") == "proprietorship" and ctx.get("proprietor_name") \
                and nb == normalize_name(ctx["proprietor_name"]):
            results[p["id"]] = {"match_class": "proprietor_match", "source": "code",
                                "reason": f"{p['name_b']} is the declared proprietor"}
        else:
            to_ai.append(p)

    if not to_ai:
        return results

    if cfg["mode"] == "live":
        listing = json.dumps([{"id": p["id"], "name_a": p["name_a"], "name_b": p["name_b"],
                               "context": p.get("context") or {}} for p in to_ai], indent=1)
        cache_key = "names:" + fingerprint(listing.encode())
        answer = db.cache_get(cache_key)
        source = "cache"
        if answer is None:
            try:
                answer, model = _call_gemini(cfg, [NAME_PROMPT + listing])
                db.cache_put(cache_key, answer)
                source = f"Gemini ({model})"
            except AIUnavailable:
                answer = None
        if answer:
            by_id = {r.get("id"): r for r in answer.get("results", []) if isinstance(r, dict)}
            for p in to_ai:
                r = by_id.get(p["id"], {})
                cls = r.get("match_class")
                if cls not in ("exact", "proprietor_match", "partial", "different"):
                    cls, reason = "partial", "AI answer missing or unclear; sent to human review"
                else:
                    reason = r.get("reason", "")
                results[p["id"]] = {"match_class": cls, "reason": reason, "source": source}
            return results

    for p in to_ai:  # offline, or AI unavailable
        cls, reason = _heuristic_match(p["name_a"], p["name_b"])
        results[p["id"]] = {"match_class": cls, "reason": reason, "source": "offline heuristic"}
    return results


# ---------------------------------------------------------------------------
# Job 3: vendor message
# ---------------------------------------------------------------------------
def template_message(vendor, fix_reasons):
    lines = "\n".join(f"{i}. {r}" for i, r in enumerate(fix_reasons, 1))
    return {"subject": f"Action needed: vendor onboarding for {vendor}",
            "body": (f"Dear {vendor} team,\n\nThank you for your onboarding submission. "
                     f"Before we can complete it, we need the following:\n\n{lines}\n\n"
                     "Please reply with the corrected details or documents using your resubmission link. "
                     "We will re-check everything as soon as we receive them.\n\n"
                     "Regards,\nVendor Onboarding Team")}


def draft_message(vendor, fix_reasons, cfg):
    if cfg["mode"] != "live":
        out = template_message(vendor, fix_reasons)
        out["source"] = "template (offline)"
        return out
    prompt = MESSAGE_PROMPT.replace("{vendor}", vendor).replace(
        "{issues}", "\n".join(f"- {r}" for r in fix_reasons))
    try:
        answer, model = _call_gemini(cfg, [prompt])
        if answer.get("subject") and answer.get("body"):
            return {"subject": answer["subject"], "body": answer["body"], "source": f"Gemini ({model})"}
    except AIUnavailable:
        pass
    out = template_message(vendor, fix_reasons)
    out["source"] = "template (AI unavailable)"
    return out
