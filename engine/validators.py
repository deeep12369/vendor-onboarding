"""
validators.py — "the maths".

Small, pure functions that check the format of Indian identifiers and clean up
names. No AI here: every function gives the same answer for the same input.
"""
import re

# ---------------------------------------------------------------------------
# Patterns (regular expressions)
# ---------------------------------------------------------------------------
# PAN: 5 letters, 4 digits, 1 letter        e.g. AAKCS1234F
PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
# GSTIN: 2-digit state + PAN + entity number + 'Z' + check character
GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
# IFSC: 4-letter bank code, a zero, 6-character branch code
IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
PHONE_RE = re.compile(r"^(\+91[\s-]?)?[6-9][0-9]{9}$")
PINCODE_RE = re.compile(r"^[1-9][0-9]{5}$")

FREE_EMAIL_DOMAINS = {"gmail.com", "yahoo.com", "yahoo.co.in", "hotmail.com",
                      "outlook.com", "rediffmail.com", "ymail.com", "proton.me"}

# GST state codes (first two digits of a GSTIN) -> state name
STATE_CODES = {
    "01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab",
    "04": "Chandigarh", "05": "Uttarakhand", "06": "Haryana", "07": "Delhi",
    "08": "Rajasthan", "09": "Uttar Pradesh", "10": "Bihar", "18": "Assam",
    "19": "West Bengal", "20": "Jharkhand", "21": "Odisha", "22": "Chhattisgarh",
    "23": "Madhya Pradesh", "24": "Gujarat", "27": "Maharashtra", "29": "Karnataka",
    "30": "Goa", "32": "Kerala", "33": "Tamil Nadu", "36": "Telangana",
    "37": "Andhra Pradesh",
}

# The 4th character of a PAN tells you what kind of holder it belongs to
PAN_HOLDER_TYPES = {"C": "company", "P": "individual", "F": "firm or LLP",
                    "H": "Hindu undivided family", "A": "association of persons",
                    "T": "trust", "B": "body of individuals", "G": "government"}
# What the 4th character should be for each entity type on the form
EXPECTED_PAN_TYPE = {"private_limited": "C", "public_limited": "C", "llp": "F",
                     "partnership": "F", "proprietorship": "P"}

ENTITY_LABELS = {"private_limited": "Private limited company",
                 "public_limited": "Public limited company", "llp": "LLP",
                 "partnership": "Partnership firm", "proprietorship": "Proprietorship"}


def clean_id(value):
    """Uppercase and strip spaces from an identifier; None stays None."""
    if value is None:
        return None
    return re.sub(r"\s+", "", str(value)).upper() or None


def pan_valid(pan):
    return bool(pan) and bool(PAN_RE.match(pan))


# ---------------------------------------------------------------------------
# GSTIN check digit
# ---------------------------------------------------------------------------
CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def gstin_check_char(first14):
    """
    Work out the 15th character of a GSTIN from the first 14.
    1. Map each character to a number: 0-9 -> 0-9, A-Z -> 10-35.
    2. Multiply alternate characters by 1 and 2.
    3. For each product, add (product // 36) + (product % 36).
    4. Check value = (36 - total % 36) % 36, turned back into a character.
    """
    total = 0
    for i, ch in enumerate(first14):
        product = CHARS.index(ch) * (1 if i % 2 == 0 else 2)
        total += product // 36 + product % 36
    return CHARS[(36 - total % 36) % 36]


def gstin_valid(gstin):
    """Returns (ok, reason)."""
    if not gstin:
        return False, "GSTIN is empty"
    if len(gstin) != 15:
        return False, f"GSTIN has {len(gstin)} characters; it must have 15"
    if not GSTIN_RE.match(gstin):
        return False, "GSTIN does not follow the pattern: state code, PAN, entity number, Z, check character"
    if gstin[:2] not in STATE_CODES:
        return False, f"GSTIN starts with {gstin[:2]}, which is not a known state code"
    expected = gstin_check_char(gstin[:14])
    if gstin[14] != expected:
        return False, f"GSTIN check character is {gstin[14]} but should be {expected}; likely a typo"
    return True, "GSTIN format and check character are valid"


def gstin_pan(gstin):
    """The PAN embedded in a GSTIN (characters 3 to 12)."""
    return gstin[2:12] if gstin and len(gstin) >= 12 else None


def gstin_state(gstin):
    return STATE_CODES.get(gstin[:2]) if gstin else None


def ifsc_valid(ifsc):
    return bool(ifsc) and bool(IFSC_RE.match(ifsc))


# ---------------------------------------------------------------------------
# Name normalisation (before any AI is used)
# ---------------------------------------------------------------------------
_REPLACEMENTS = {
    "PVT": "PRIVATE", "PVT.": "PRIVATE", "PRIV": "PRIVATE",
    "LTD": "LIMITED", "LTD.": "LIMITED", "LIMITD": "LIMITED",
    "CO": "COMPANY", "CORP": "CORPORATION", "&": "AND",
    "INDS": "INDUSTRIES", "IND": "INDUSTRIES", "ENT": "ENTERPRISES",
}
_DROP = {"M/S", "MS", "MESSRS", "THE", "SHRI", "SRI", "MR", "MRS", "SMT"}


def normalize_name(name):
    """
    Clean a business or person name so trivial differences disappear:
    uppercase, '&' -> AND, punctuation removed, 'M/S' dropped,
    'PVT' -> PRIVATE, 'LTD' -> LIMITED, extra spaces collapsed.
    """
    if not name:
        return ""
    s = str(name).upper().replace("&", " AND ").replace("M/S", " ")
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    tokens = [_REPLACEMENTS.get(t, t) for t in s.split()]
    tokens = [t for t in tokens if t not in _DROP]
    return " ".join(tokens)


def mask(value, keep=4):
    """Show only the last few characters, e.g. ...7890 (used in vendor messages)."""
    if not value:
        return ""
    value = str(value)
    return "…" + value[-keep:] if len(value) > keep else value
