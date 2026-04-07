"""
backend/resume_parser.py
========================
Parse resume files (PDF, DOCX) to extract text.
Score resume text against job keywords and apply threshold.
"""
import io
import re
import logging

logger = logging.getLogger(__name__)

# Default threshold: candidate must score >= this (0-100) to pass
DEFAULT_THRESHOLD = 50


def extract_text_from_pdf(data: bytes) -> str:
    """Extract text from PDF bytes."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        parts = []
        for page in reader.pages:
            t = page.extract_text()
            if t:
                parts.append(t)
        return "\n".join(parts).strip()
    except Exception as e:
        logger.warning("PDF extraction failed: %s", e)
        return ""


def extract_text_from_docx(data: bytes) -> str:
    """Extract text from DOCX bytes."""
    try:
        from docx import Document
        doc = Document(io.BytesIO(data))
        return "\n".join(p.text for p in doc.paragraphs if p.text).strip()
    except Exception as e:
        logger.warning("DOCX extraction failed: %s", e)
        return ""


def parse_resume(data: bytes, filename: str) -> dict:
    """
    Parse resume file and return extracted text + metadata.
    Returns: {"text": str, "word_count": int, "parse_ok": bool}
    """
    filename_lower = (filename or "").lower()
    text = ""

    if filename_lower.endswith(".pdf"):
        text = extract_text_from_pdf(data)
    elif filename_lower.endswith(".docx") or filename_lower.endswith(".doc"):
        text = extract_text_from_docx(data)
    else:
        # Try PDF first, then DOCX
        text = extract_text_from_pdf(data) or extract_text_from_docx(data)

    text = (text or "").strip()
    words = re.findall(r"\b\w+\b", text)
    return {
        "text": text,
        "word_count": len(words),
        "parse_ok": len(text) > 0,
    }


def score_resume(text: str, keywords: list) -> dict:
    """
    Score resume text against a list of keywords (e.g. skills, job requirements).
    Returns: {"score": 0-100, "matched": [...], "missing": [...], "above_threshold": bool}
    """
    if not keywords:
        return {"score": 100, "matched": [], "missing": [], "above_threshold": True}

    text_lower = text.lower()
    normalized = [k.strip().lower() for k in keywords if k and k.strip()]
    matched = []
    missing = []
    for k in normalized:
        if k in text_lower:
            matched.append(k)
        else:
            missing.append(k)

    score = round(100 * len(matched) / len(normalized)) if normalized else 100
    return {
        "score": min(100, score),
        "matched": matched,
        "missing": missing,
        "above_threshold": True,  # set by caller with threshold
    }


def evaluate_resume(
    data: bytes,
    filename: str,
    keywords: list = None,
    threshold: float = None,
) -> dict:
    """
    Parse resume and score against keywords. Apply threshold.
    Returns: {
        "parse": {"text": ..., "word_count": ..., "parse_ok": ...},
        "score": {"score": 0-100, "matched": [...], "missing": [...]},
        "above_threshold": bool,
        "threshold": float,
    }
    """
    threshold = threshold if threshold is not None else DEFAULT_THRESHOLD
    keywords = keywords or []

    parsed = parse_resume(data, filename)
    scored = score_resume(parsed["text"], keywords)
    above = scored["score"] >= threshold
    scored["above_threshold"] = above

    return {
        "parse": parsed,
        "score": scored,
        "above_threshold": above,
        "threshold": threshold,
    }
