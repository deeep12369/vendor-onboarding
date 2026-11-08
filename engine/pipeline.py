"""
pipeline.py — "the conductor".

Runs the stages in order, tells the screen what is happening (via on_event),
and saves everything to the database. It never makes a decision itself:
the AI reads, the rules check, decision.py decides.
"""
import random
import time

from . import ai, db, mockdata, rules
from .ai import DOC_LABELS
from .decision import decide
from .validators import clean_id, gstin_pan, gstin_state

STAGES = [
    ("intake", "Submission received", "Check the form is filled in"),
    ("tagging", "Tag and extract", "AI identifies each file and reads its fields"),
    ("completeness", "Completeness", "Are all required documents here, and the right type?"),
    ("format", "Format checks", "PAN, GSTIN check digit, IFSC, contact details"),
    ("triangulation", "Triangulation", "Does every fact agree across form, documents and registries?"),
    ("authenticity", "Authenticity", "Do the PDFs show signs of editing?"),
    ("risk", "Risk checks", "Reused bank account, duplicate vendor, contact email"),
    ("decision", "Decision", "Worst severity sets the status; message drafted"),
]

ID_FORM_FIELDS = {"pan", "gstin", "ifsc"}


def clean_submission(sub):
    out = {}
    for k, v in sub.items():
        if isinstance(v, str):
            v = v.strip()
        if k in ID_FORM_FIELDS:
            v = clean_id(v)
        if k == "account_number" and v:
            v = "".join(ch for ch in str(v) if ch.isdigit())
        out[k] = v if v not in ("", None) else None
    return out


def pick_documents(files):
    """For each document type, keep the best-identified, most readable file."""
    best = {}
    for d in files:
        t = d.get("doc_type")
        if t in (None, "aadhaar", "other") or (d.get("doc_type_confidence") or 0) < rules.CONF:
            continue
        if t not in best or d["doc_type_confidence"] > best[t]["doc_type_confidence"]:
            best[t] = d
    return best


def triangulation_matrix(ctx):
    """The grid the screen shows: each fact × each source."""
    s, docs, reg, penny = ctx["sub"], ctx["docs"], ctx["registry"] or {}, ctx["penny"] or {}
    f = rules.field
    gst, pan, chq = docs.get("gst_certificate"), docs.get("pan_card"), docs.get("cancelled_cheque")
    prop = s.get("entity_type") == "proprietorship"
    return [
        {"Fact": "PAN", "Form": s.get("pan"), "PAN card": f(pan, "pan"),
         "GST certificate": gstin_pan(f(gst, "gstin")), "Cheque": None,
         "GST registry": gstin_pan(s.get("gstin")) if reg else None, "Bank (penny-drop)": None, "rule": "T01"},
        {"Fact": "Legal name", "Form": s.get("proprietor_name") if prop else s.get("legal_name"),
         "PAN card": f(pan, "name"), "GST certificate": f(gst, "legal_name"), "Cheque": None,
         "GST registry": reg.get("legal_name"), "Bank (penny-drop)": None, "rule": "T02"},
        {"Fact": "State", "Form": s.get("state"), "PAN card": None, "GST certificate": f(gst, "state"),
         "Cheque": None, "GST registry": reg.get("state") or gstin_state(s.get("gstin")),
         "Bank (penny-drop)": None, "rule": "T03"},
        {"Fact": "Account number", "Form": s.get("account_number"), "PAN card": None, "GST certificate": None,
         "Cheque": f(chq, "account_number"), "GST registry": None,
         "Bank (penny-drop)": s.get("account_number") if penny.get("verified") else None, "rule": "T04"},
        {"Fact": "Account holder", "Form": s.get("legal_name"), "PAN card": None, "GST certificate": None,
         "Cheque": f(chq, "account_holder_name"), "GST registry": None,
         "Bank (penny-drop)": penny.get("holder_name"), "rule": "T05"},
        {"Fact": "GST status", "Form": None, "PAN card": None, "GST certificate": None, "Cheque": None,
         "GST registry": reg.get("status") or "Not found", "Bank (penny-drop)": None, "rule": "T06"},
    ]


def build_message(sub, decision, results, cfg):
    vendor = sub.get("legal_name") or "Vendor"
    fix_msgs = []
    for r in results:
        if not r["passed"] and r["severity"] == "FIX" and r.get("vendor_msg") and r["vendor_msg"] not in fix_msgs:
            fix_msgs.append(r["vendor_msg"])
    if decision["status"] == "Rejected":
        # Neutral on purpose: never tell a suspected fraudster which check failed
        return {"to": "vendor", "source": "template",
                "subject": f"Update on your vendor onboarding — {vendor}",
                "body": (f"Dear {vendor} team,\n\nThank you for your submission. We are unable to complete your "
                         "onboarding based on the information provided. If you believe this is an error, please "
                         "contact our procurement team directly.\n\nRegards,\nVendor Onboarding Team")}
    if fix_msgs:
        msg = ai.draft_message(vendor, fix_msgs, cfg)
        msg["to"] = "vendor"
        return msg
    if decision["status"] == "Pending":
        return {"to": "vendor", "source": "template",
                "subject": f"Your vendor onboarding is under review — {vendor}",
                "body": (f"Dear {vendor} team,\n\nThank you for your submission. It is now with our procurement "
                         "team for a final review. We will be in touch within two working days.\n\n"
                         "Regards,\nVendor Onboarding Team")}
    code = f"VND-{random.randint(10000, 99999)}"
    return {"to": "vendor", "source": "template", "vendor_code": code,
            "subject": f"Welcome aboard — {vendor} ({code})",
            "body": (f"Dear {vendor} team,\n\nYour onboarding is complete. Your vendor code is {code}; please "
                     "quote it on every invoice.\n\nRegards,\nVendor Onboarding Team")}


def run(submission, files, cfg, case_label="Custom", on_event=None):
    """
    submission: dict of form fields
    files:      list of (file_name, file_bytes)
    cfg:        {"mode": "live"|"offline", "api_key": ..., "model": ...}
    on_event:   callback(kind, stage, payload) used by the screen for the live view
    """
    emit = on_event or (lambda *a: None)
    t0 = time.time()
    sub = clean_submission(submission)
    run_id = db.new_run_id()
    previous = db.latest_run_for_vendor(sub.get("legal_name"))
    db.start_run(run_id, sub.get("legal_name"), case_label, cfg["mode"], previous)
    cfg = dict(cfg, on_wait=lambda m: emit("wait", "tagging", m))
    ctx = {"sub": sub, "files": [], "docs": {}, "registry": None, "penny": None, "names": {}}
    all_results = []

    def stage(key, fn):
        emit("stage_start", key, None)
        results = fn()
        all_results.extend(results)
        emit("stage_done", key, results)
        return results

    # 1. Intake
    stage("intake", lambda: rules.stage_intake(ctx))

    # 2. Tag and extract — one AI call per file
    emit("stage_start", "tagging", None)
    for name, data in files:
        emit("file_start", "tagging", name)
        try:
            out = ai.extract_document(data, name, cfg)
        except ai.AIUnavailable as exc:
            out = {"doc_type": None, "doc_type_confidence": 0.0, "fields": {}, "quality_issue": None,
                   "notes": f"AI unavailable: {str(exc)[:160]}", "source": "error",
                   "sha256": ai.fingerprint(data), "seconds": 0}
        out["file_name"] = name
        out["_bytes"] = data
        if out.get("doc_type") == "aadhaar":
            out["fields"] = {}           # never keep anything from an Aadhaar card
        ctx["files"].append(out)
        db.log_event(run_id, "ai", "document_tagged",
                     f"{name} → {DOC_LABELS.get(out.get('doc_type'))} ({out.get('doc_type_confidence')}) via {out.get('source')}")
        emit("file_done", "tagging", out)
    tag_results = rules.stage_tagging(ctx)
    all_results.extend(tag_results)
    emit("stage_done", "tagging", tag_results)
    ctx["docs"] = pick_documents(ctx["files"])

    # 3–4. Completeness and format
    stage("completeness", lambda: rules.stage_completeness(ctx))
    stage("format", lambda: rules.stage_format(ctx))

    # 5. Triangulation — look up the outside world, then compare
    def triangulate():
        ctx["registry"] = mockdata.gst_lookup(sub.get("gstin"))
        ctx["penny"] = mockdata.penny_drop(sub.get("account_number"), sub.get("ifsc"))
        db.log_event(run_id, "system", "lookups",
                     f"GST registry: {'found' if ctx['registry'] else 'not found'}; penny-drop: {ctx['penny']['message']}")
        pairs = rules.name_pairs(ctx)
        ctx["names"] = ai.match_names(pairs, cfg)
        for pid, m in ctx["names"].items():
            db.log_event(run_id, "ai" if "Gemini" in m.get("source", "") else "system", "name_match",
                         f"{pid}: {m['match_class']} via {m.get('source')}")
        return rules.stage_triangulation(ctx)
    tri = stage("triangulation", triangulate)

    # 6–7. Authenticity and risk
    stage("authenticity", lambda: rules.stage_authenticity(ctx, tri))
    stage("risk", lambda: rules.stage_risk(ctx))

    # 8. Decision
    emit("stage_start", "decision", None)
    decision = decide(all_results)
    message = build_message(sub, decision, all_results, cfg)
    documents = [{k: v for k, v in d.items() if k != "_bytes"} for d in ctx["files"]]
    result = {"run_id": run_id, "case_label": case_label, "ai_mode": cfg["mode"], "submission": sub,
              **decision, "rules": all_results, "documents": documents,
              "matrix": triangulation_matrix(ctx), "names": ctx["names"],
              "registry": ctx["registry"], "penny": ctx["penny"], "message": message,
              "previous_run_id": previous, "seconds": round(time.time() - t0, 1)}
    db.finish_run(run_id, result)
    db.log_event(run_id, "system", "message_drafted", f"{message['subject']} (via {message.get('source')})")
    emit("stage_done", "decision", [])
    emit("done", "decision", result)
    return result
