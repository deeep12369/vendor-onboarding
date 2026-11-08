"""
decision.py — "the judge".

The worst severity among failed rules decides the status:
    any BLOCK  -> Rejected
    any REVIEW -> Pending (needs human review)
    any FIX    -> Pending (awaiting vendor)
    otherwise  -> Approved
"""
RANK = {"BLOCK": 3, "REVIEW": 2, "FIX": 1, "INFO": 0, "PASS": -1}


def decide(results):
    failed = [r for r in results if not r["passed"]]
    worst = max((RANK[r["severity"]] for r in failed), default=-1)
    if worst == 3:
        status, flag = "Rejected", "Fraud or eligibility risk"
    elif worst == 2:
        status, flag = "Pending", "Needs human review"
    elif worst == 1:
        status, flag = "Pending", "Awaiting vendor"
    else:
        status, flag = "Approved", None
    top = [r for r in failed if RANK[r["severity"]] == worst and worst >= 1]
    top_reason = top[0]["reason"] if top else "All checks passed"
    return {"status": status, "flag": flag, "top_reason": top_reason,
            "counts": {sev: sum(1 for r in failed if r["severity"] == sev) for sev in ("BLOCK", "REVIEW", "FIX", "INFO")}}
