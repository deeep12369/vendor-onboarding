# Vendor Onboarding — from submission to approval

A working process that takes a vendor submission (a short form plus **unlabelled** documents) and returns
**Approved**, **Pending** or **Rejected**, with every reason visible and a ready-to-send vendor message.

**Rules decide, AI assists.** Google Gemini tags each document and reads its fields; plain Python rules make
every decision, so the same input always gives the same verdict, with a written reason.

## The process

1. **Submission received** — form fields filled?
2. **Tag and extract** (AI) — what is each file, and what does it say? Each field carries a confidence.
3. **Completeness** — PAN card, GST certificate and cancelled cheque all present, and the right type?
4. **Format checks** — PAN pattern, GSTIN check digit, IFSC, contact details.
5. **Triangulation** — does each fact agree across the form, the documents, the GST registry and the bank?
6. **Authenticity** — do the PDFs show signs of editing?
7. **Risk checks** — bank account reused by another vendor, duplicate vendor, webmail with high spend.
8. **Decision** — worst severity wins: BLOCK → Rejected, REVIEW/FIX → Pending, else Approved.

## Demo cases (`test_cases/`)

| Case | What it tests | Expected |
|---|---|---|
| V0 Happy path | Meaningless file names; every source agrees | Approved |
| V1 Wrong document | Aadhaar instead of PAN card; blurred cheque | Pending (awaiting vendor) |
| V2 Tampered certificate | Certificate edited to match the form; registry disagrees; PDF saved by Photoshop | Rejected |
| V3a Proprietor's account | Bank account in the proprietor's own name | Approved with note |
| V3b Stranger's account | Bank account belongs to someone named nowhere | Pending (needs human review) |
| V4 Recycled account | Bank account already belongs to another vendor | Rejected |

All companies, people, numbers and documents are fictional and marked SPECIMEN.
Regenerate them with `python scripts/make_test_docs.py`.

## Run it on Windows

1. Install Python from python.org — tick **"Add python.exe to PATH"** on the first screen.
2. Open this folder, click the address bar, type `cmd`, press Enter.
3. Run, one line at a time:
   ```
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```
4. Copy `.streamlit\secrets.toml.example` to `.streamlit\secrets.toml` and paste your Gemini key into it.
   (Without a key the app still runs, in offline mode.)
5. Start it: `streamlit run app.py` — it opens at http://localhost:8501.

Next time, only steps 2, `.venv\Scripts\activate` and step 5 are needed.

## Put it online (Streamlit Community Cloud)

1. Upload this folder to a GitHub repository (the `secrets.toml` file is excluded by `.gitignore`).
2. At share.streamlit.io: **Create app** → your repository → branch `main` → main file `app.py`.
3. **Advanced settings → Secrets**: `GEMINI_API_KEY = "your-key"` → **Deploy**.

## AI modes

- **Live** — Gemini reads every document. Answers are cached by each file's SHA-256 fingerprint, so a repeat
  file costs no call. Rate limits (error 429) are retried with growing waits.
- **Offline** — stored sample answers for the demo files, plus code-only name matching and template
  messages. A sidebar switch; use it if Gemini is slow during a live demo, and say so.
- If a live call fails on a demo file, the stored answer is used and labelled
  "offline sample answer (Gemini unavailable)".

## Code map

| File | Job |
|---|---|
| `app.py` | Navigation |
| `views/submit.py` | Form, demo-case loader, live run view |
| `views/dashboard.py` | Counts and every run |
| `views/detail.py` | One run's evidence, history, audit log, reviewer override |
| `views/how_it_works.py` | The design on one page |
| `engine/pipeline.py` | Runs the stages in order |
| `engine/ai.py` | Every Gemini call |
| `engine/rules.py` | All rules |
| `engine/validators.py` | PAN/GSTIN/IFSC checks, name cleaning |
| `engine/authenticity.py` | PDF metadata check |
| `engine/decision.py` | Worst severity → status |
| `engine/db.py` | SQLite storage and audit log |
| `engine/mockdata.py` | Mock GST registry, penny-drop, vendor master |
| `data/` | The mock data and offline answers |

## Five-minute demo script

1. **(30s)** The problem: manual review, manual chasing, no audit trail. The principle: rules decide, AI assists.
2. **(90s)** Load **V0**, run it. Point at the files being tagged despite meaningless names, the stages ticking
   through, and the triangulation grid all green.
3. **(60s)** Load **V1**, run it. Aadhaar flagged and not stored; PAN card missing; cheque blurred.
   Open **Vendor message**: one complete, specific list.
4. **(60s)** Load **V2**, run it. The certificate matches the form, but the GST registry names a different
   company, and the PDF was saved by Photoshop: Rejected. Show the neutral vendor note.
5. **(60s)** Dashboard → open a run → audit log and reviewer override. What's next: real GST and penny-drop
   APIs, a reviewer queue, thresholds tuned from override data.
