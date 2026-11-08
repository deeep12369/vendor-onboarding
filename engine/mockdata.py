"""
mockdata.py — "the outside world, simulated".

In production these would be API calls to a GST Suvidha Provider (GSP), a
bank-account verification (penny-drop) provider, and the company's ERP.
Here they read small JSON/CSV files, but each function has the same inputs
and outputs a real integration would have, so swapping one in touches only
this file.
"""
import csv
import json
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"


@lru_cache(maxsize=None)
def _gst_registry():
    return json.loads((DATA / "gst_registry.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def _bank_accounts():
    return json.loads((DATA / "bank_accounts.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def _vendor_master():
    with open(DATA / "vendor_master.csv", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


@lru_cache(maxsize=None)
def _ifsc_banks():
    with open(DATA / "ifsc_master.csv", newline="", encoding="utf-8") as f:
        return {row["bank_code"]: row["bank_name"] for row in csv.DictReader(f)}


def gst_lookup(gstin):
    """Like a GSP 'search taxpayer' call: returns legal name, trade name, state, status — or None."""
    return _gst_registry().get(gstin)


def penny_drop(account_number, ifsc):
    """Like a penny-drop API: ₹1 is 'deposited' and the bank returns the holder name — or None."""
    rec = _bank_accounts().get(f"{account_number}|{ifsc}")
    if rec is None:
        return {"verified": False, "holder_name": None,
                "message": "Bank could not verify this account and IFSC"}
    return {"verified": True, "holder_name": rec["holder_name"],
            "message": "Account active; holder name returned by bank"}


def bank_name_for_ifsc(ifsc):
    return _ifsc_banks().get(ifsc[:4]) if ifsc else None


def vendors_with_account(account_number):
    return [v for v in _vendor_master() if v["account_number"] == account_number]


def vendors_with_pan_or_gstin(pan, gstin):
    return [v for v in _vendor_master() if (pan and v["pan"] == pan) or (gstin and v["gstin"] == gstin)]


def vendor_master():
    return _vendor_master()
