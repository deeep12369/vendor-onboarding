"""
rules.py — "the rulebook".

Every rule returns the same shape:
  {"rule": "T01", "stage": "triangulation", "passed": False, "severity": "BLOCK",
   "reason": "...", "evidence": {...}, "vendor_msg": "..." (only for fixable issues)}

Severity (what a FAILED rule does to the outcome):
  BLOCK  -> fraud or eligibility signal -> Rejected
  REVIEW -> needs a human judgment call  -> Pending (needs human review)
  FIX    -> the vendor can correct it    -> Pending (awaiting vendor)
  INFO   -> logged only
A passed rule has severity "PASS".

All rules always run, so the vendor gets one complete list of issues.
Adding a rule = writing one function and calling it from its stage.
"""
from . import mockdata
from .ai import DOC_LABELS
from .authenticity import pdf_metadata_check
from .validators import (EMAIL_RE, ENTITY_LABELS, EXPECTED_PAN_TYPE, FREE_EMAIL_DOMAINS,
                         PAN_HOLDER_TYPES, PHONE_RE, PINCODE_RE, gstin_pan, gstin_state,
                         gstin_valid, ifsc_valid, mask, normalize_name, pan_valid)

CONF = 0.8  # minimum confidence for an AI-read value to be trusted
REQUIRED_DOCS = ["pan_card", "gst_certificate", "cancelled_cheque"]
KEY_FIELDS = {"gst_certificate": ["legal_name", "gstin", "state"],
              "pan_card": ["name", "pan"],
              "cancelled_cheque": ["account_number", "ifsc"],
              "msme_certificate": ["enterprise_name"]}
REQUIRED_FORM = ["legal_name", "entity_type", "pan", "gstin", "address", "city", "state",
                 "pincode", "contact_name", "email", "phone", "account_number", "ifsc",
                 "account_holder_name"]
FIELD_LABELS = {"legal_name": "legal name", "entity_type": "entity type", "pan": "PAN",
                "gstin": "GSTIN", "address": "address", "city": "city", "state": "state",
                "pincode": "pincode", "contact_name": "contact name", "email": "email",
                "phone": "phone", "account_number": "bank account number", "ifsc": "IFSC",
                "account_holder_name": "account holder name", "proprietor_name": "proprietor name"}


NICE = {"account_number": "account number", "ifsc": "IFSC", "legal_name": "legal name", "gstin": "GSTIN",
        "state": "state", "name": "name", "pan": "PAN", "enterprise_name": "enterprise name"}


def join_and(items):
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def res(rule, stage, passed, severity, reason, evidence=None, vendor_msg=None, note=None):
    return {"rule": rule, "stage": stage, "passed": passed,
            "severity": "PASS" if passed else severity, "reason": reason,
            "evidence": evidence or {}, "vendor_msg": None if passed else vendor_msg, "note": note}


def field(doc, name):
    """A value read by the AI, only if its confidence clears the bar."""
    if not doc:
        return None
    item = doc.get("fields", {}).get(name) or {}
    return item.get("value") if (item.get("confidence") or 0) >= CONF else None


def same(a, b):
    return (a or "").strip().lower() == (b or "").strip().lower()


# ---------------------------------------------------------------------------
# Stage 1 — intake
# ---------------------------------------------------------------------------
def stage_intake(ctx):
    s = ctx["sub"]
    required = REQUIRED_FORM + (["proprietor_name"] if s.get("entity_type") == "proprietorship" else [])
    missing = [f for f in required if not s.get(f)]
    if missing:
        names = ", ".join(FIELD_LABELS.get(f, f) for f in missing)
        return [res("F01", "intake", False, "FIX", f"Missing form fields: {names}",
                    {"missing": missing}, f"Please fill in the missing form fields: {names}.")]
    return [res("F01", "intake", True, "", "All required form fields are filled")]


# ---------------------------------------------------------------------------
# Stage 2 — tag and extract (the AI has already run; these rules check its output)
# ---------------------------------------------------------------------------
def stage_tagging(ctx):
    out = []
    for d in ctx["files"]:
        name, dtype, conf = d["file_name"], d.get("doc_type"), d.get("doc_type_confidence") or 0
        if dtype is None or conf < CONF:
            out.append(res("D01", "tagging", False, "FIX",
                           f"Could not identify '{name}' (confidence {conf:.2f})",
                           {"file": name, "guess": dtype, "confidence": conf},
                           f"We could not tell what the file '{name}' is. Please re-upload it as a clear, complete scan."))
            continue
        out.append(res("D01", "tagging", True, "",
                       f"'{name}' identified as {DOC_LABELS[dtype]} (confidence {conf:.2f})",
                       {"file": name, "doc_type": dtype, "confidence": conf}))
        if dtype in ("aadhaar", "other"):
            out.append(res("D03", "tagging", False, "INFO",
                           f"'{name}' is an {DOC_LABELS[dtype]}, which is not needed; it was not used or stored",
                           {"file": name, "doc_type": dtype}))
            continue
        unreadable = [f for f in KEY_FIELDS.get(dtype, []) if field(d, f) is None]
        issue = d.get("quality_issue")
        if unreadable or issue:
            what = join_and(NICE.get(f, f) for f in unreadable) if unreadable else "some fields"
            out.append(res("D02", "tagging", False, "FIX",
                           f"{DOC_LABELS[dtype]} '{name}' is {issue or 'hard to read'}; unreadable: {what}",
                           {"file": name, "quality_issue": issue, "unreadable_fields": unreadable},
                           f"The {DOC_LABELS[dtype].lower()} you sent ('{name}') is {issue or 'hard to read'}, so we could not read "
                           f"the {what}. Please upload a clearer copy."))
        else:
            out.append(res("D02", "tagging", True, "", f"All key fields on {DOC_LABELS[dtype]} read with confidence ≥ {CONF}"))
    return out


# ---------------------------------------------------------------------------
# Stage 3 — completeness
# ---------------------------------------------------------------------------
def stage_completeness(ctx):
    out, s = [], ctx["sub"]
    present = {d.get("doc_type") for d in ctx["files"]}
    missing = [t for t in REQUIRED_DOCS if t not in present]
    extras = [DOC_LABELS[t] for t in present if t in ("aadhaar", "other")]
    if missing:
        names = join_and(DOC_LABELS[t] for t in missing)
        instead = f" We received {join_and('an ' + e if e[0] in 'AEIOU' else 'a ' + e for e in extras)} instead, which we do not need." if extras else ""
        out.append(res("C01", "completeness", False, "FIX", f"Missing required documents: {names}",
                       {"missing": missing, "received": sorted(t for t in present if t)},
                       f"Please upload your {names}.{instead}"))
    else:
        out.append(res("C01", "completeness", True, "", "PAN card, GST certificate and cancelled cheque all present"))

    pan, entity = s.get("pan"), s.get("entity_type")
    if pan_valid(pan) and entity in EXPECTED_PAN_TYPE:
        actual, expected = pan[3], EXPECTED_PAN_TYPE[entity]
        if actual != expected:
            holder = PAN_HOLDER_TYPES.get(actual, "unknown holder type")
            out.append(res("C02", "completeness", False, "FIX",
                           f"PAN 4th character '{actual}' means {holder}; a {ENTITY_LABELS[entity]} needs '{expected}'",
                           {"pan": pan, "entity_type": entity},
                           f"The PAN you gave belongs to a {holder}, but your business is registered as a "
                           f"{ENTITY_LABELS[entity].lower()}. Please give the {'proprietor' if entity == 'proprietorship' else 'business'}'s PAN."))
        else:
            out.append(res("C02", "completeness", True, "", f"PAN holder type fits a {ENTITY_LABELS[entity]}"))
    return out


# ---------------------------------------------------------------------------
# Stage 4 — format checks
# ---------------------------------------------------------------------------
def stage_format(ctx):
    s, out = ctx["sub"], []
    pan = s.get("pan")
    out.append(res("F02", "format", pan_valid(pan), "FIX",
                   "PAN format valid" if pan_valid(pan) else f"PAN '{pan}' is not 5 letters, 4 digits, 1 letter",
                   {"pan": pan}, "The PAN in your form is not in the right format (e.g. ABCDE1234F). Please check it."))
    ok, why = gstin_valid(s.get("gstin"))
    out.append(res("F03", "format", ok, "FIX", why, {"gstin": s.get("gstin")},
                   "The GSTIN in your form is not valid (it may contain a typo). Please check it against your GST certificate."))
    ifsc = s.get("ifsc")
    bank = mockdata.bank_name_for_ifsc(ifsc)
    good = ifsc_valid(ifsc) and bank is not None
    out.append(res("F04", "format", good, "FIX",
                   f"IFSC valid ({bank})" if good else f"IFSC '{ifsc}' is malformed or the bank code is unknown",
                   {"ifsc": ifsc, "bank": bank}, "The IFSC in your form is not valid. Please check it on your cheque."))
    bad = []
    if not EMAIL_RE.match(s.get("email") or ""):
        bad.append("email")
    if not PHONE_RE.match((s.get("phone") or "").replace(" ", "")):
        bad.append("phone")
    if not PINCODE_RE.match(s.get("pincode") or ""):
        bad.append("pincode")
    out.append(res("F05", "format", not bad, "FIX",
                   "Email, phone and pincode formats valid" if not bad else f"Invalid format: {', '.join(bad)}",
                   {"invalid": bad}, f"Please correct the {', '.join(bad)} in your form."))
    return out


# ---------------------------------------------------------------------------
# Stage 5 — triangulation
# ---------------------------------------------------------------------------
def name_pairs(ctx):
    """Which names need comparing. The AI judges only the pairs code cannot settle."""
    s, docs, reg = ctx["sub"], ctx["docs"], ctx["registry"]
    proprietor = s.get("entity_type") == "proprietorship"
    context = {"entity_type": s.get("entity_type"), "proprietor_name": s.get("proprietor_name")}
    pairs = []
    if reg:
        reg_name = reg.get("trade_name") if proprietor and reg.get("trade_name") else reg["legal_name"]
        pairs.append({"id": "form_vs_registry", "name_a": s.get("legal_name"), "name_b": reg_name, "context": context})
        if proprietor:
            pairs.append({"id": "proprietor_vs_registry", "name_a": s.get("proprietor_name"),
                          "name_b": reg["legal_name"], "context": context})
        cert_name = field(docs.get("gst_certificate"), "legal_name")
        if cert_name:
            pairs.append({"id": "certificate_vs_registry", "name_a": cert_name, "name_b": reg["legal_name"], "context": context})
    cert_name = field(docs.get("gst_certificate"), "legal_name")
    if cert_name:
        target = s.get("proprietor_name") if proprietor else s.get("legal_name")
        pairs.append({"id": "certificate_vs_form", "name_a": target, "name_b": cert_name, "context": context})
    pan_name = field(docs.get("pan_card"), "name")
    if pan_name:
        target = s.get("proprietor_name") if proprietor else s.get("legal_name")
        pairs.append({"id": "pan_card_vs_form", "name_a": target, "name_b": pan_name, "context": context})
    penny = ctx.get("penny") or {}
    if penny.get("verified"):
        pairs.append({"id": "bank_holder_vs_form", "name_a": s.get("legal_name"),
                      "name_b": penny["holder_name"], "context": context})
    return [p for p in pairs if p["name_a"] and p["name_b"]]


def stage_triangulation(ctx):
    s, docs, reg, names, out = ctx["sub"], ctx["docs"], ctx["registry"], ctx["names"], []
    gst_doc, pan_doc, chq = docs.get("gst_certificate"), docs.get("pan_card"), docs.get("cancelled_cheque")

    # T01 — PAN across sources
    sources = {"form": s.get("pan"), "GSTIN on form": gstin_pan(s.get("gstin")),
               "PAN card": field(pan_doc, "pan"), "GST certificate": gstin_pan(field(gst_doc, "gstin"))}
    seen = {k: v for k, v in sources.items() if v}
    involved = [k for k, v in seen.items() if v != s.get("pan")]
    out.append(res("T01", "triangulation", len(set(seen.values())) <= 1, "BLOCK",
                   "PAN agrees across " + ", ".join(seen) if len(set(seen.values())) <= 1
                   else "PAN differs between sources: " + "; ".join(f"{k} {v}" for k, v in seen.items()),
                   {"sources": seen, "documents_involved": involved}))

    # T02 — legal name across sources
    checked = [(pid, names[pid]) for pid in ("form_vs_registry", "proprietor_vs_registry", "certificate_vs_registry",
                                             "certificate_vs_form", "pan_card_vs_form") if pid in names]
    worst, problems = "PASS", []
    for pid, m in checked:
        cls = m["match_class"]
        if cls == "different" and "registry" in pid:
            sev = "BLOCK"
        elif cls in ("partial", "different"):
            sev = "REVIEW"
        else:
            continue
        what = {"form_vs_registry": "Form vs GST registry", "proprietor_vs_registry": "Proprietor vs GST registry",
                "certificate_vs_registry": "GST certificate vs GST registry", "certificate_vs_form": "GST certificate vs form",
                "pan_card_vs_form": "PAN card vs form"}[pid]
        problems.append(f"{what}: '{m.get('name_a')}' vs '{m.get('name_b')}' ({cls})")
        worst = sev if worst != "BLOCK" else worst
    evidence = {"registry_legal_name": reg.get("legal_name") if reg else None,
                "form": s.get("legal_name"), "gst_certificate": field(gst_doc, "legal_name"),
                "pan_card": field(pan_doc, "name"),
                "comparisons": {pid: m for pid, m in checked},
                "documents_involved": ["GST certificate"] if any("certificate" in p for p in problems) else []}
    out.append(res("T02", "triangulation", not problems, worst,
                   "Legal name agrees across form, documents and registry" if not problems
                   else "Name mismatch. " + "; ".join(problems), evidence))

    # T03 — state across sources
    states = {"form address": s.get("state"), "GSTIN state code": gstin_state(s.get("gstin")),
              "GST certificate": field(gst_doc, "state"), "GST registry": reg.get("state") if reg else None}
    seen = {k: v for k, v in states.items() if v}
    agree = len({v.strip().lower() for v in seen.values()}) <= 1
    out.append(res("T03", "triangulation", agree, "BLOCK",
                   "State agrees: " + next(iter(seen.values()), "") if agree
                   else "State differs between sources: " + "; ".join(f"{k} {v}" for k, v in seen.items()),
                   {"sources": seen, "documents_involved": [] if agree else ["GST certificate"]}))

    # T04 — bank details: form vs cheque
    chq_acct, chq_ifsc = field(chq, "account_number"), field(chq, "ifsc")
    if chq and (chq_acct or chq_ifsc) and s.get("account_number"):
        acct_ok = chq_acct is None or chq_acct == s.get("account_number")
        ifsc_ok = chq_ifsc is None or chq_ifsc == s.get("ifsc")
        msgs = []
        if not acct_ok:
            msgs.append(f"The account number on your cancelled cheque ({mask(chq_acct)}) does not match the one "
                        f"in your form ({mask(s.get('account_number'))}).")
        if not ifsc_ok:
            msgs.append(f"The IFSC on your cheque ({chq_ifsc}) does not match your form ({s.get('ifsc')}).")
        out.append(res("T04", "triangulation", acct_ok and ifsc_ok, "FIX",
                       "Account number and IFSC match the cheque" if acct_ok and ifsc_ok else " ".join(msgs),
                       {"form": {"account": s.get("account_number"), "ifsc": s.get("ifsc")},
                        "cheque": {"account": chq_acct, "ifsc": chq_ifsc}},
                       " ".join(msgs) + " Please confirm the correct account and upload a matching cancelled cheque."))

    # T05 — penny-drop holder name
    penny = ctx.get("penny") or {}
    if not s.get("account_number") or not s.get("ifsc"):
        out.append(res("T05", "triangulation", False, "FIX",
                       "Bank not checked: the form has no account number or IFSC yet (see F01)", {},
                       "Please enter your bank account number and IFSC."))
    elif not penny.get("verified"):
        out.append(res("T05", "triangulation", False, "REVIEW", penny.get("message", "Bank verification not available"),
                       {"penny_drop": penny}))
    else:
        m = names.get("bank_holder_vs_form", {"match_class": "partial", "reason": "not compared"})
        cls = m["match_class"]
        ok = cls in ("exact", "proprietor_match")
        note = f"Account is in the proprietor's own name ({penny['holder_name']})" if cls == "proprietor_match" else None
        out.append(res("T05", "triangulation", ok, "REVIEW",
                       f"Bank says holder is '{penny['holder_name']}' — {cls}: {m['reason']}",
                       {"penny_drop": penny, "form_name": s.get("legal_name"), "match": m}, note=note))

    # T06 — GST registry status
    if not gstin_valid(s.get("gstin"))[0]:
        # Nothing valid to look up: the format rule (F03) already asks the vendor to fix it
        out.append(res("T06", "triangulation", False, "FIX",
                       "GST registry not checked: the form has no valid GSTIN yet (see F03)",
                       {"gstin": s.get("gstin")}, "Please enter your GSTIN exactly as it appears on your GST certificate."))
    elif not reg:
        # A well-formed GSTIN that the registry does not know: could be a typo or a brand-new
        # registration, or a made-up number. A person checks it on the GST portal.
        out.append(res("T06", "triangulation", False, "REVIEW",
                       f"GSTIN {s.get('gstin')} not found in the GST registry (demo registry holds only the demo vendors)",
                       {"gstin": s.get("gstin")}))
    else:
        active = reg.get("status") == "Active"
        out.append(res("T06", "triangulation", active, "BLOCK",
                       f"GSTIN is {reg.get('status')} in the GST registry", {"registry": reg}))
    return out


# ---------------------------------------------------------------------------
# Stage 6 — authenticity
# ---------------------------------------------------------------------------
def stage_authenticity(ctx, triangulation_results):
    out = []
    conflicted = set()
    for r in triangulation_results:
        if not r["passed"]:
            conflicted.update(r["evidence"].get("documents_involved", []))
    pdfs = [d for d in ctx["files"] if d["file_name"].lower().endswith(".pdf") and d.get("doc_type") not in ("aadhaar", "other")]
    for d in pdfs:
        meta = pdf_metadata_check(d["_bytes"])
        d["metadata"] = meta
        label = DOC_LABELS.get(d.get("doc_type"))
        if not meta["flags"]:
            out.append(res("A01", "authenticity", True, "",
                           f"{label} '{d['file_name']}': no signs of editing (producer: {meta['producer'] or 'not recorded'})",
                           {"metadata": meta}))
            continue
        also_failed = label in conflicted
        out.append(res("A01", "authenticity", False, "BLOCK" if also_failed else "REVIEW",
                       f"{label} '{d['file_name']}': " + "; ".join(meta["flags"]) +
                       (" — and its contents fail triangulation" if also_failed else " — weak signal alone"),
                       {"metadata": meta, "combined_with_triangulation_failure": also_failed}))
    if not pdfs:
        out.append(res("A01", "authenticity", True, "", "No PDF documents to check (images carry no reliable metadata)"))
    return out


# ---------------------------------------------------------------------------
# Stage 7 — risk
# ---------------------------------------------------------------------------
def stage_risk(ctx):
    s, out = ctx["sub"], []
    others = [v for v in mockdata.vendors_with_account(s.get("account_number"))
              if normalize_name(v["vendor_name"]) != normalize_name(s.get("legal_name"))]
    out.append(res("A02", "risk", not others, "BLOCK",
                   "Bank account is not linked to any other vendor" if not others
                   else "Bank account already belongs to existing vendor(s): " +
                        ", ".join(f"{v['vendor_name']} ({v['vendor_code']})" for v in others),
                   {"matches": others}))
    dupes = mockdata.vendors_with_pan_or_gstin(s.get("pan"), s.get("gstin"))
    out.append(res("A03", "risk", not dupes, "REVIEW",
                   "PAN and GSTIN are not already onboarded" if not dupes
                   else "Possible duplicate: " + ", ".join(f"{v['vendor_name']} ({v['vendor_code']})" for v in dupes),
                   {"matches": dupes}))
    domain = (s.get("email") or "").split("@")[-1].lower()
    spend = float(s.get("expected_annual_spend_inr") or 0)
    flag = domain in FREE_EMAIL_DOMAINS and spend > 1_000_000
    out.append(res("A04", "risk", not flag, "INFO",
                   f"Free webmail ({domain}) with expected spend ₹{spend:,.0f}" if flag else "Contact email check passed",
                   {"domain": domain, "expected_spend": spend}))
    return out
