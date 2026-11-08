"""
authenticity.py — "the tamper check".

Every PDF quietly records which software produced it and when it was created
and last modified. A government certificate saved by an image editor or an
online PDF editor, or modified long after it was created, is suspicious.

This is a weak signal on its own (people legitimately re-save and compress
files), so the rules treat it as REVIEW alone, and BLOCK only when the same
document also fails a triangulation check.
"""
import io
from datetime import timedelta

from pypdf import PdfReader

EDITING_TOOLS = ["photoshop", "gimp", "canva", "ilovepdf", "smallpdf", "pdfescape",
                 "sejda", "pdf-xchange", "foxit phantompdf", "nitro", "inkscape",
                 "pdfelement", "sodapdf", "word", "libreoffice"]


def pdf_metadata_check(file_bytes):
    """Returns a dict: what the metadata says and any red flags found."""
    result = {"checked": False, "producer": None, "creator": None,
              "created": None, "modified": None, "flags": []}
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        meta = reader.metadata or {}
    except Exception as exc:  # unreadable PDF
        result["flags"].append(f"PDF could not be opened for a metadata check ({exc.__class__.__name__})")
        return result

    result["checked"] = True
    producer = str(meta.get("/Producer") or "")
    creator = str(meta.get("/Creator") or "")
    result["producer"], result["creator"] = producer or None, creator or None

    created = modified = None
    try:
        created = meta.creation_date
        modified = meta.modification_date
    except Exception:
        pass
    result["created"] = created.isoformat() if created else None
    result["modified"] = modified.isoformat() if modified else None

    tool_text = f"{producer} {creator}".lower()
    for tool in EDITING_TOOLS:
        if tool in tool_text:
            result["flags"].append(f"Saved by an editing tool ({producer or creator})")
            break
    if created and modified and modified - created > timedelta(days=1):
        days = (modified - created).days
        result["flags"].append(f"Modified {days} days after it was created")
    return result
