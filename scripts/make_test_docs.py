"""
make_test_docs.py — generates every piece of fictional test data.

Run once:  python scripts/make_test_docs.py
Creates:
  data/gst_registry.json, data/bank_accounts.json, data/vendor_master.csv,
  data/ifsc_master.csv, data/offline_answers.json
  test_cases/<case>/submission.json + document files with meaningless names

All companies, people, numbers and documents are FICTIONAL and marked SPECIMEN.
"""
import csv
import hashlib
import io
import json
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from pypdf import PdfReader, PdfWriter
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from engine.validators import gstin_check_char  # noqa: E402

DATA, CASES = ROOT / "data", ROOT / "test_cases"
FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")


def font(size, bold=False, mono=False):
    name = "DejaVuSansMono.ttf" if mono else ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")
    try:
        return ImageFont.truetype(str(FONT_DIR / name), size)
    except OSError:
        return ImageFont.load_default(size)


def make_gstin(state_code, pan):
    first14 = f"{state_code}{pan}1Z"
    return first14 + gstin_check_char(first14)


# ---------------------------------------------------------------------------
# The cases (single source of truth)
# ---------------------------------------------------------------------------
def build_cases():
    v0 = dict(legal_name="Sharma Packaging Private Limited", entity_type="private_limited", proprietor_name="",
              pan="AAKCS1234F", state_code="07", address="Plot 42, Okhla Industrial Area Phase II",
              city="New Delhi", state="Delhi", pincode="110020", contact_name="Rohit Sharma",
              email="rohit@sharmapack.in", phone="9811023456", account_number="50100234567890",
              ifsc="HDFC0000123", account_holder_name="Sharma Packaging Pvt Ltd",
              category="Packaging", expected_annual_spend_inr=2500000)
    v1 = dict(legal_name="Mehta Hardware", entity_type="partnership", proprietor_name="",
              pan="AAHFM5521K", state_code="06", address="Shop 7, Sector 14 Market",
              city="Gurugram", state="Haryana", pincode="122001", contact_name="Vikram Mehta",
              email="accounts@mehtahardware.in", phone="9876501234", account_number="912010045671234",
              ifsc="UTIB0000456", account_holder_name="Mehta Hardware",
              category="Hardware and tools", expected_annual_spend_inr=800000)
    v2 = dict(legal_name="Apex Office Supplies Private Limited", entity_type="private_limited", proprietor_name="",
              pan="AADCK7788Q", state_code="09", address="B-118, Sector 63",
              city="Noida", state="Uttar Pradesh", pincode="201301", contact_name="Sanjay Rao",
              email="procurement.apexoffice@gmail.com", phone="9958812345", account_number="33445566778",
              ifsc="SBIN0001234", account_holder_name="Apex Office Supplies Pvt Ltd",
              category="Office supplies", expected_annual_spend_inr=4500000)
    v3 = dict(legal_name="Gupta Electricals", entity_type="proprietorship", proprietor_name="Amit Gupta",
              pan="ABCPG4821M", state_code="09", address="22, Gwynne Road, Aminabad",
              city="Lucknow", state="Uttar Pradesh", pincode="226018", contact_name="Amit Gupta",
              email="guptaelectricals.lko@gmail.com", phone="9415012345", account_number="0123104567890",
              ifsc="PUNB0012300", account_holder_name="Gupta Electricals",
              category="Electrical supplies", expected_annual_spend_inr=600000)
    v3b = dict(v3, account_number="50200098765432", ifsc="HDFC0004567")
    v4 = dict(legal_name="Nova Prints Private Limited", entity_type="private_limited", proprietor_name="",
              pan="AAFCN3344R", state_code="27", address="Unit 12, Marol Industrial Estate, Andheri East",
              city="Mumbai", state="Maharashtra", pincode="400069", contact_name="Karan Shah",
              email="karan@novaprints.in", phone="9820012345", account_number="918020045678123",
              ifsc="ICIC0000789", account_holder_name="Nova Prints Pvt Ltd",
              category="Printing", expected_annual_spend_inr=1800000)

    return [
        {"key": "V0_happy_path", "title": "V0 · Happy path — Sharma Packaging", "form": v0,
         "expected": "Approved",
         "story": "Clean submission with meaningless file names. Every source agrees; 'Pvt Ltd' matches 'Private Limited'.",
         "registry": {"legal_name": "SHARMA PACKAGING PRIVATE LIMITED", "trade_name": "SHARMA PACKAGING"},
         "penny": "SHARMA PACKAGING PRIVATE LIMITED",
         "files": [("scan001.pdf", "gst", {}), ("IMG_2034.jpg", "pan", {"name": "SHARMA PACKAGING PRIVATE LIMITED"}),
                   ("doc3.png", "cheque", {"printed": "SHARMA PACKAGING PVT LTD"})]},
        {"key": "V1_wrong_document", "title": "V1 · Wrong document — Mehta Hardware", "form": v1,
         "expected": "Pending (awaiting vendor)",
         "story": "An Aadhaar card instead of the PAN card, and a blurred cheque. Tagging catches both; the message asks for exactly what is missing.",
         "registry": {"legal_name": "MEHTA HARDWARE", "trade_name": "MEHTA HARDWARE"},
         "penny": "MEHTA HARDWARE",
         "files": [("GST_reg.pdf", "gst", {}), ("aadhar_front.jpg", "aadhaar", {"name": "Vikram Mehta"}),
                   ("cheque_scan.jpg", "cheque", {"printed": "MEHTA HARDWARE", "blur": True})]},
        {"key": "V2_tampered_certificate", "title": "V2 · Tampered certificate — Apex Office Supplies", "form": v2,
         "expected": "Rejected",
         "story": "The GST certificate's name was edited to match the form, but the registry holds a different company for that GSTIN, and the PDF was saved by an image editor.",
         "registry": {"legal_name": "KALRA INDUSTRIAL TRADERS PRIVATE LIMITED", "trade_name": "KALRA TRADERS"},
         "penny": "APEX OFFICE SUPPLIES PVT LTD",
         "files": [("certificate.pdf", "gst", {"tampered": True}),
                   ("pan.jpg", "pan", {"name": "APEX OFFICE SUPPLIES PRIVATE LIMITED"}),
                   ("cheque.png", "cheque", {"printed": "APEX OFFICE SUPPLIES PVT LTD"})]},
        {"key": "V3a_proprietor_account", "title": "V3a · Proprietor's own account — Gupta Electricals", "form": v3,
         "expected": "Approved (with note)",
         "story": "The bank account is in the proprietor's personal name. For a proprietorship that is normal, so it passes with a note.",
         "registry": {"legal_name": "AMIT GUPTA", "trade_name": "GUPTA ELECTRICALS"},
         "penny": "AMIT GUPTA",
         "files": [("gst.pdf", "gst", {}), ("pancard.jpg", "pan", {"name": "AMIT GUPTA", "person": True}),
                   ("cancelled_cheque.jpg", "cheque", {"printed": "AMIT GUPTA"})]},
        {"key": "V3b_stranger_account", "title": "V3b · Stranger's account — Gupta Electricals", "form": v3b,
         "expected": "Pending (needs human review)",
         "story": "Same vendor, but the bank account belongs to Neha Verma, who is named nowhere in the submission.",
         "registry": None,
         "penny": "NEHA VERMA",
         "files": [("gst.pdf", "gst", {}), ("pancard.jpg", "pan", {"name": "AMIT GUPTA", "person": True}),
                   ("cancelled_cheque.jpg", "cheque", {"printed": "NEHA VERMA"})]},
        {"key": "V4_recycled_account", "title": "V4 · Recycled bank account — Nova Prints", "form": v4,
         "expected": "Rejected",
         "story": "The bank account already belongs to an existing vendor, Nova Traders. Only a check across vendors can see this.",
         "registry": {"legal_name": "NOVA PRINTS PRIVATE LIMITED", "trade_name": "NOVA PRINTS"},
         "penny": "NOVA TRADERS",
         "files": [("registration.pdf", "gst", {}), ("pan_scan.jpg", "pan", {"name": "NOVA PRINTS PRIVATE LIMITED"}),
                   ("IMG_5521.png", "cheque", {"printed": "NOVA PRINTS PVT LTD"})]},
    ]


BANKS = {"HDFC": "HDFC Bank", "ICIC": "ICICI Bank", "SBIN": "State Bank of India", "UTIB": "Axis Bank",
         "PUNB": "Punjab National Bank", "KKBK": "Kotak Mahindra Bank", "BARB": "Bank of Baroda", "YESB": "Yes Bank"}
STATE_NAMES = {"07": "Delhi", "06": "Haryana", "09": "Uttar Pradesh", "27": "Maharashtra"}
CONSTITUTION = {"private_limited": "Private Limited Company", "partnership": "Partnership",
                "proprietorship": "Proprietorship"}


# ---------------------------------------------------------------------------
# Document makers
# ---------------------------------------------------------------------------
def gst_certificate_pdf(form, gstin, legal, trade, tampered=False):
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    c.setFillColor(HexColor("#1f3b6f"))
    c.setFont("Helvetica-Bold", 13)
    c.drawCentredString(w / 2, h - 60, "Government of India")
    c.setFont("Helvetica-Bold", 15)
    c.drawCentredString(w / 2, h - 82, "Form GST REG-06")
    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(w / 2, h - 102, "Registration Certificate")
    c.setFillColor(HexColor("#000000"))
    c.setFont("Helvetica", 10)
    c.drawString(60, h - 140, f"Registration Number:  {gstin}")
    rows = [("1. Legal Name", legal), ("2. Trade Name, if any", trade),
            ("3. Constitution of Business", CONSTITUTION[form["entity_type"]]),
            ("4. Address of Principal Place of Business",
             f"{form['address']}, {form['city']}, {form['state']} - {form['pincode']}"),
            ("5. Date of Liability", "01/04/2019"), ("6. Date of Validity", "From 01/04/2019 To Not Applicable"),
            ("7. Type of Registration", "Regular"),
            ("8. Particulars of Approving Authority", "Signature not verified — Specimen")]
    y = h - 180
    for label, value in rows:
        c.setStrokeColor(HexColor("#999999"))
        c.rect(55, y - 10, w - 110, 30, stroke=1, fill=0)
        c.setFont("Helvetica-Bold", 9.5)
        c.drawString(62, y + 3, label)
        c.setFont("Helvetica", 9.5)
        c.drawString(270, y + 3, value[:62])
        y -= 30
    c.setFont("Helvetica", 9)
    c.drawString(60, y - 30, f"State: {form['state']}")
    c.drawString(60, y - 45, "Date of issue of Certificate: 12/04/2019")
    c.saveState()
    c.setFillColor(HexColor("#d9534f"))
    c.setFillAlpha(0.18)
    c.setFont("Helvetica-Bold", 70)
    c.translate(w / 2, h / 2 - 80)
    c.rotate(35)
    c.drawCentredString(0, 0, "SPECIMEN")
    c.restoreState()
    c.setFont("Helvetica-Oblique", 8)
    c.drawCentredString(w / 2, 40, "Fictional test document generated for a case study. Not a real certificate.")
    c.save()

    # Set the hidden metadata: a normal portal export, or signs of editing
    reader = PdfReader(io.BytesIO(buf.getvalue()))
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    created = datetime(2019, 4, 12, 10, 15, 0)
    if tampered:
        modified = datetime(2026, 10, 28, 22, 41, 0)
        producer, creator = "Adobe Photoshop 25.1 (Windows)", "Adobe Photoshop 25.1 (Windows)"
    else:
        modified, producer, creator = created, "iText 5.5.13 ©2000-2020 iText Group NV", "GST Portal"
    fmt = lambda d: d.strftime("D:%Y%m%d%H%M%S+05'30'")
    writer.add_metadata({"/Producer": producer, "/Creator": creator,
                         "/CreationDate": fmt(created), "/ModDate": fmt(modified),
                         "/Title": "Registration Certificate"})
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def specimen_stamp(img, text="SPECIMEN", size=90):
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    f = font(size, bold=True)
    tw = d.textlength(text, font=f)
    d.text(((img.width - tw) / 2, img.height / 2 - size / 2), text, font=f, fill=(200, 40, 40, 60))
    layer = layer.rotate(18, center=(img.width / 2, img.height / 2))
    return Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")


def pan_card_image(name, pan, person=False):
    img = Image.new("RGB", (900, 560), (218, 234, 246))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 900, 70], fill=(36, 84, 140))
    d.text((24, 20), "INCOME TAX DEPARTMENT", font=font(26, bold=True), fill="white")
    d.text((620, 24), "GOVT. OF INDIA", font=font(22, bold=True), fill="white")
    d.text((24, 92), "Permanent Account Number Card", font=font(22), fill=(30, 30, 30))
    d.text((24, 135), pan, font=font(44, bold=True, mono=True), fill=(10, 10, 10))
    d.text((24, 215), "Name", font=font(18), fill=(70, 70, 70))
    d.text((24, 240), name, font=font(28, bold=True), fill=(10, 10, 10))
    if person:
        d.text((24, 300), "Father's Name", font=font(18), fill=(70, 70, 70))
        d.text((24, 325), "RAMESH GUPTA", font=font(26, bold=True), fill=(10, 10, 10))
        d.text((24, 385), "Date of Birth", font=font(18), fill=(70, 70, 70))
        d.text((24, 410), "14/08/1984", font=font(26, bold=True), fill=(10, 10, 10))
        d.rectangle([700, 110, 860, 300], outline=(90, 90, 90), width=2, fill=(200, 210, 220))
        d.text((735, 195), "PHOTO", font=font(22), fill=(110, 110, 110))
    else:
        d.text((24, 300), "Date of Incorporation/Formation", font=font(18), fill=(70, 70, 70))
        d.text((24, 325), "18/06/2016", font=font(26, bold=True), fill=(10, 10, 10))
    d.line([620, 470, 860, 470], fill=(60, 60, 60), width=2)
    d.text((660, 478), "Signature", font=font(16), fill=(70, 70, 70))
    d.text((24, 520), "Fictional test document for a case study", font=font(14), fill=(120, 120, 120))
    return specimen_stamp(img)


def cheque_image(form, printed, blur=False):
    img = Image.new("RGB", (1500, 660), (236, 244, 236))
    d = ImageDraw.Draw(img)
    bank = BANKS[form["ifsc"][:4]]
    d.rectangle([0, 0, 1500, 90], fill=(28, 96, 74))
    d.text((30, 22), bank.upper(), font=font(40, bold=True), fill="white")
    d.text((30, 105), f"Branch: {form['city']}    IFSC: {form['ifsc']}", font=font(24), fill=(20, 20, 20))
    d.text((1150, 105), "Date  __ __ ____", font=font(24), fill=(20, 20, 20))
    d.text((30, 180), "Pay", font=font(26), fill=(20, 20, 20))
    d.line([100, 210, 1300, 210], fill=(90, 90, 90), width=2)
    d.text((30, 250), "Rupees", font=font(26), fill=(20, 20, 20))
    d.line([140, 280, 1100, 280], fill=(90, 90, 90), width=2)
    d.rectangle([1150, 240, 1460, 300], outline=(90, 90, 90), width=2)
    d.text((1160, 252), "₹", font=font(30), fill=(20, 20, 20))
    d.text((30, 340), f"A/c No.  {form['account_number']}", font=font(32, bold=True, mono=True), fill=(10, 10, 10))
    d.text((1000, 400), f"For {printed}", font=font(24, bold=True), fill=(10, 10, 10))
    d.text((1060, 480), "Authorised Signatory", font=font(20), fill=(60, 60, 60))
    micr = f"⑈{form['account_number'][-6:]}⑈ 110240{form['ifsc'][-3:]}⑆ {form['account_number'][:6]}⑈ 31"
    d.text((240, 590), micr.replace("⑈", "|").replace("⑆", ":"), font=font(30, mono=True), fill=(30, 30, 30))
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    ld.line([200, 520, 1250, 160], fill=(180, 20, 20, 220), width=6)
    ld.line([220, 560, 1270, 200], fill=(180, 20, 20, 220), width=6)
    ld.text((520, 300), "CANCELLED", font=font(90, bold=True), fill=(180, 20, 20, 200))
    img = Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")
    d = ImageDraw.Draw(img)
    d.text((30, 630), "SPECIMEN — fictional test document for a case study", font=font(16), fill=(120, 120, 120))
    if blur:
        img = img.filter(ImageFilter.GaussianBlur(radius=7))
    return img


def aadhaar_image(name):
    img = Image.new("RGB", (900, 560), (250, 250, 250))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 900, 80], fill=(240, 150, 60))
    d.text((300, 22), "Government of India", font=font(30, bold=True), fill="white")
    d.rectangle([40, 120, 230, 340], outline=(120, 120, 120), width=2, fill=(225, 225, 225))
    d.text((90, 215), "PHOTO", font=font(24), fill=(130, 130, 130))
    d.text((270, 130), name, font=font(30, bold=True), fill=(20, 20, 20))
    d.text((270, 185), "DOB: 03/02/1979", font=font(24), fill=(20, 20, 20))
    d.text((270, 230), "MALE", font=font(24), fill=(20, 20, 20))
    d.text((230, 430), "XXXX XXXX 0000", font=font(48, bold=True, mono=True), fill=(20, 20, 20))
    d.rectangle([0, 510, 900, 560], fill=(200, 40, 40))
    d.text((200, 520), "Aadhaar — specimen, fictional test document", font=font(20, bold=True), fill="white")
    return specimen_stamp(img)


def to_bytes(img, name):
    buf = io.BytesIO()
    if name.lower().endswith((".jpg", ".jpeg")):
        img.save(buf, "JPEG", quality=88)
    else:
        img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def conf_field(value, confidence=0.97):
    return {"value": value, "confidence": confidence}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    cases = build_cases()
    if CASES.exists():
        shutil.rmtree(CASES)
    CASES.mkdir(parents=True)
    DATA.mkdir(exist_ok=True)

    registry, accounts, offline = {}, {}, {}
    for case in cases:
        form = dict(case["form"])
        gstin = make_gstin(form.pop("state_code"), form["pan"])
        form["gstin"] = gstin
        state = STATE_NAMES[gstin[:2]]
        if case["registry"]:
            registry[gstin] = {"gstin": gstin, "legal_name": case["registry"]["legal_name"],
                               "trade_name": case["registry"]["trade_name"], "state": state,
                               "status": "Active", "registration_date": "2019-04-01",
                               "constitution": CONSTITUTION[form["entity_type"]]}
        accounts[f"{form['account_number']}|{form['ifsc']}"] = {"holder_name": case["penny"],
                                                                "bank": BANKS[form["ifsc"][:4]]}
        reg = registry.get(gstin)
        folder = CASES / case["key"]
        folder.mkdir()
        sub = {k: v for k, v in form.items()}
        (folder / "submission.json").write_text(json.dumps(
            {"title": case["title"], "expected": case["expected"], "story": case["story"], "form": sub},
            indent=2), encoding="utf-8")

        for fname, kind, opts in case["files"]:
            if kind == "gst":
                legal = form["legal_name"].upper() if opts.get("tampered") else reg["legal_name"]
                trade = form["legal_name"].upper() if opts.get("tampered") else reg["trade_name"]
                data = gst_certificate_pdf(form, gstin, legal, trade, tampered=opts.get("tampered", False))
                answer = {"doc_type": "gst_certificate", "doc_type_confidence": 0.98, "quality_issue": None,
                          "notes": "Form GST REG-06 registration certificate (specimen).",
                          "fields": {"legal_name": conf_field(legal), "trade_name": conf_field(trade),
                                     "gstin": conf_field(gstin, 0.98), "state": conf_field(form["state"], 0.95),
                                     "registration_date": conf_field("01/04/2019", 0.9)}}
            elif kind == "pan":
                data = to_bytes(pan_card_image(opts["name"], form["pan"], opts.get("person", False)), fname)
                answer = {"doc_type": "pan_card", "doc_type_confidence": 0.97, "quality_issue": None,
                          "notes": "Income Tax PAN card (specimen).",
                          "fields": {"name": conf_field(opts["name"]), "pan": conf_field(form["pan"], 0.98)}}
            elif kind == "cheque":
                blur = opts.get("blur", False)
                data = to_bytes(cheque_image(form, opts["printed"], blur), fname)
                if blur:
                    answer = {"doc_type": "cancelled_cheque", "doc_type_confidence": 0.9, "quality_issue": "blurred",
                              "notes": "A cancelled cheque, but too blurred to read the numbers reliably.",
                              "fields": {"account_holder_name": conf_field(opts["printed"], 0.62),
                                         "account_number": conf_field(None, 0.2), "ifsc": conf_field(None, 0.3),
                                         "bank_name": conf_field(BANKS[form["ifsc"][:4]], 0.85)}}
                else:
                    answer = {"doc_type": "cancelled_cheque", "doc_type_confidence": 0.97, "quality_issue": None,
                              "notes": "Cancelled cheque (specimen).",
                              "fields": {"account_holder_name": conf_field(opts["printed"], 0.95),
                                         "account_number": conf_field(form["account_number"], 0.96),
                                         "ifsc": conf_field(form["ifsc"], 0.96),
                                         "bank_name": conf_field(BANKS[form["ifsc"][:4]], 0.97)}}
            elif kind == "aadhaar":
                data = to_bytes(aadhaar_image(opts["name"]), fname)
                answer = {"doc_type": "aadhaar", "doc_type_confidence": 0.97, "quality_issue": None,
                          "notes": "An Aadhaar card; no fields read on purpose.", "fields": {}}
            (folder / fname).write_bytes(data)
            offline[hashlib.sha256(data).hexdigest()] = answer
        print(f"{case['key']}: GSTIN {gstin}, files {[f[0] for f in case['files']]}")

    # Existing vendors (the company's vendor master). Nova Traders owns V4's bank account.
    v4 = next(c for c in cases if c["key"].startswith("V4"))["form"]
    master = [
        ("VND-10021", "Nova Traders", "AAKFN9021H", "27", v4["account_number"], v4["ifsc"]),
        ("VND-10022", "Bharat Steel Fabricators Private Limited", "AABCB4410L", "06", "50100987654321", "HDFC0000890"),
        ("VND-10023", "Kaveri Logistics", "AAJFK7812P", "29", "38291029384", "SBIN0004321"),
        ("VND-10024", "Shree Ganesh Caterers", "BKLPS6634D", "27", "917010023456789", "UTIB0000123"),
        ("VND-10025", "Pioneer IT Services Private Limited", "AADCP5523R", "36", "001105012345", "ICIC0000111"),
        ("VND-10026", "Green Leaf Housekeeping LLP", "AAOFG1187M", "07", "1234567890123", "KKBK0000222"),
        ("VND-10027", "Orient Paper Mills Private Limited", "AACCO3345B", "19", "20145678901", "BARB0SALTLA"),
        ("VND-10028", "Delta Security Services", "AAFFD7765K", "09", "60123456789", "PUNB0099900"),
        ("VND-10029", "Rao Stationery Mart", "BQWPR2231C", "29", "34567890123", "SBIN0007766"),
        ("VND-10030", "Metro Courier Solutions Private Limited", "AAGCM8890E", "07", "50200011223344", "HDFC0000777"),
    ]
    with open(DATA / "vendor_master.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["vendor_code", "vendor_name", "pan", "gstin", "account_number", "ifsc"])
        for code, name, pan, st, acct, ifsc in master:
            w.writerow([code, name, pan, make_gstin(st, pan), acct, ifsc])
            accounts.setdefault(f"{acct}|{ifsc}", {"holder_name": name.upper(), "bank": BANKS[ifsc[:4]]})
    with open(DATA / "ifsc_master.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["bank_code", "bank_name"])
        for code, name in BANKS.items():
            w.writerow([code, name])
    # Nova Traders' account is the one Nova Prints lists; the bank knows it as Nova Traders
    accounts[f"{v4['account_number']}|{v4['ifsc']}"] = {"holder_name": "NOVA TRADERS", "bank": "ICICI Bank"}

    (DATA / "gst_registry.json").write_text(json.dumps(registry, indent=2), encoding="utf-8")
    (DATA / "bank_accounts.json").write_text(json.dumps(accounts, indent=2), encoding="utf-8")
    (DATA / "offline_answers.json").write_text(json.dumps(offline, indent=2), encoding="utf-8")
    print(f"Wrote {len(registry)} registry entries, {len(accounts)} bank accounts, {len(offline)} offline answers")


if __name__ == "__main__":
    main()
