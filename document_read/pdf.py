"""
PDF → list of PNG images using pymupdf.
Each page is rendered at 2x zoom for better Claude readability.
"""
import fitz  # pymupdf


_ZOOM = 2.0  # higher = better quality, larger payload
_MATRIX = fitz.Matrix(_ZOOM, _ZOOM)


def pdf_bytes_to_images(pdf_bytes: bytes) -> list[bytes]:
    """Return one PNG bytes object per page."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    images = []
    for page in doc:
        pix = page.get_pixmap(matrix=_MATRIX)
        images.append(pix.tobytes("png"))
    doc.close()
    return images


def pdf_has_text_layer(pdf_bytes: bytes, min_chars: int = 100) -> bool:
    """Return True if the PDF has a meaningful embedded text layer."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    total_chars = sum(len(page.get_text()) for page in doc)
    doc.close()
    return total_chars >= min_chars


def pdf_extract_text(pdf_bytes: bytes) -> tuple[str, float]:
    """
    Extract text from a text-layer PDF.
    Returns (text, confidence) — confidence is 1.0 for clean text layer,
    lower if very few characters found.
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages = [page.get_text() for page in doc]
    doc.close()
    full_text = "\n\n".join(pages).strip()
    chars = len(full_text)
    confidence = 1.0 if chars >= 500 else (0.85 if chars >= 100 else 0.5)
    return full_text, confidence
