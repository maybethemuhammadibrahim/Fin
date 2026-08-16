"""[B] Render a PDF page to PNG bytes, optionally with a highlight box. Phase 7.

Three jobs, and the second one is the interesting one:

1. **`render_highlighted`** — a page, at a readable DPI, with a translucent
   rectangle over the clause. `bbox=None` renders the page with no highlight
   instead of failing (ADR-005): a page with no box is a usable answer, an
   exception on a dashboard is not.

2. **`typeset_pdf`** — the answer to known issue #28. EDGAR serves **HTML**, and
   `data_sourcing` writes it to disk as `.txt`, so the primary corpus has no PDF
   to point at. Rather than leaving the product's headline feature unavailable on
   its own contracts, the extracted text is typeset into a PDF *we* generate:
   deterministic, page-numbered, and searchable by the same
   `page.search_for()` the locator already uses. See ADR-021 — the rendered page
   is labelled in both frontends as typeset from the filing's text, never
   presented as the original document.

3. **`ensure_pdf`** — get *a* PDF for a document, whichever of those two it is,
   and cache it on disk so a page view is not a download plus a re-typeset.

Nothing here interprets anything. It turns bytes into other bytes.

Import note: `import pymupdf`, never `import fitz` (known issue #12).
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import pymupdf

log = logging.getLogger(__name__)

#: 150 is legible on a laptop without making a 2 MB PNG out of one page.
DEFAULT_DPI = 150

#: Amber, matching the mockup's highlight. Alpha comes from `fill_opacity`, so
#: the text underneath stays readable rather than being painted over.
HIGHLIGHT_FILL = (1.0, 0.85, 0.35)
HIGHLIGHT_STROKE = (0.85, 0.55, 0.0)
HIGHLIGHT_OPACITY = 0.35

#: Typeset page geometry, in PDF points (A4 is 595x842).
PAGE_WIDTH, PAGE_HEIGHT = 595.0, 842.0
MARGIN = 56.0
FONT_NAME = "Times-Roman"  # a base-14 font: no file to ship, identical everywhere
FONT_SIZE = 10.5
LINE_HEIGHT = 14.0

#: Where `ensure_pdf` keeps what it built. Under data/, which is gitignored —
#: everything here is reproducible from the document, so losing it costs a
#: re-render and nothing else.
CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "cache" / "pdf"


# ---------------------------------------------------------------------------
# 1. rendering
# ---------------------------------------------------------------------------


def render_highlighted(
    pdf_path: str | Path | bytes,
    page: int,
    bbox: list[float] | None,
    dpi: int = DEFAULT_DPI,
) -> bytes | None:
    """One page as PNG bytes, with `bbox` highlighted when there is one.

    `page` is **1-indexed**, matching `clause_references.source_page` and what
    the user is told on screen. `bbox` is `[x0, y0, x1, y1]` in PDF points, the
    shape `clause_locator` returns.

    Returns `None` rather than raising — an unreadable PDF, a page number past
    the end of the document, a storage miss. The caller shows the quote without
    a picture, which is exactly what it does for an ungrounded clause anyway.
    """
    document = _open(pdf_path)
    if document is None:
        return None

    try:
        index = page - 1
        if not 0 <= index < document.page_count:
            log.info("page %s is outside a %s-page document", page, document.page_count)
            return None

        target = document[index]
        if bbox:
            rect = pymupdf.Rect(*[float(v) for v in bbox])
            # Draw *behind* nothing — MuPDF paints in order, so a filled rect
            # here would cover the text. `fill_opacity` keeps it readable, and a
            # slight expansion stops the box clipping ascenders and descenders.
            target.draw_rect(
                rect + (-2, -2, 2, 2),
                color=HIGHLIGHT_STROKE,
                fill=HIGHLIGHT_FILL,
                width=1.0,
                fill_opacity=HIGHLIGHT_OPACITY,
                stroke_opacity=0.9,
            )

        pixmap = target.get_pixmap(dpi=dpi)
        return pixmap.tobytes("png")
    except Exception as exc:  # pragma: no cover - defensive, never crash a page view
        log.warning("could not render page %s: %s", page, exc)
        return None
    finally:
        document.close()


def page_count(pdf_path: str | Path | bytes) -> int:
    """How many pages, or 0 if it cannot be opened."""
    document = _open(pdf_path)
    if document is None:
        return 0
    try:
        return int(document.page_count)
    finally:
        document.close()


def _open(source: str | Path | bytes):
    try:
        if isinstance(source, bytes):
            return pymupdf.open(stream=source, filetype="pdf")
        return pymupdf.open(str(source))
    except Exception as exc:
        log.warning("cannot open PDF (%s): %s", type(source).__name__, exc)
        return None


# ---------------------------------------------------------------------------
# 2. typesetting a text-only document (ADR-021, known issue #28)
# ---------------------------------------------------------------------------


def typeset_pdf(text: str, *, title: str = "", width_chars: int = 96) -> bytes:
    """Lay plain text out as a PDF, deterministically.

    Deliberately dumb: a fixed page size, one base-14 font, hard-wrapped lines,
    a page number in the footer. No HTML parsing, no styling, no reflow that
    depends on a library version. Two runs over the same text must produce the
    same page breaks, because a clause located on page 4 has to still be on
    page 4 tomorrow.

    The output is a genuine PDF, so `page.search_for()` finds quotes in it and
    `render_highlighted` can box them — which is the entire point.
    """
    document = pymupdf.open()
    lines = _wrap(text, width_chars)
    usable_height = PAGE_HEIGHT - 2 * MARGIN - LINE_HEIGHT  # room for the footer
    per_page = max(int(usable_height // LINE_HEIGHT), 1)

    header = " ".join((title or "").split())[:110]

    for start in range(0, max(len(lines), 1), per_page):
        page = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
        y = MARGIN

        if header:
            page.insert_text(
                (MARGIN, y), header, fontname="Helvetica-Oblique", fontsize=8, color=(0.45, 0.45, 0.45)
            )
        y += LINE_HEIGHT

        for line in lines[start : start + per_page]:
            if line:
                page.insert_text((MARGIN, y), line, fontname=FONT_NAME, fontsize=FONT_SIZE)
            y += LINE_HEIGHT

        page.insert_text(
            (MARGIN, PAGE_HEIGHT - MARGIN / 2),
            f"typeset from the filing's text · page {document.page_count}",
            fontname="Helvetica",
            fontsize=7.5,
            color=(0.55, 0.55, 0.55),
        )

    return document.tobytes()


def _wrap(text: str, width: int) -> list[str]:
    """Hard-wrap on word boundaries, keeping blank lines as paragraph breaks.

    Written out rather than using `textwrap` so the behaviour on a 400-character
    unbroken token (a table of dots, a URL) is explicit: it is cut, not allowed
    to run off the page where `search_for` would never find it.
    """
    out: list[str] = []
    for raw in (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        stripped = raw.strip()
        if not stripped:
            out.append("")
            continue
        line = ""
        for word in stripped.split():
            while len(word) > width:
                if line:
                    out.append(line)
                    line = ""
                out.append(word[:width])
                word = word[width:]
            if not line:
                line = word
            elif len(line) + 1 + len(word) <= width:
                line = f"{line} {word}"
            else:
                out.append(line)
                line = word
        if line:
            out.append(line)
    return out


# ---------------------------------------------------------------------------
# 3. getting a PDF for a document, whatever it arrived as
# ---------------------------------------------------------------------------


def ensure_pdf(
    *,
    storage_url: str | None,
    extracted_text: str | None,
    filename: str = "",
    file_type: str | None = None,
) -> tuple[Path, bool] | None:
    """A PDF on disk for this document, and whether it was typeset by us.

    Order: the real PDF from storage if there is one, otherwise a typeset render
    of the extracted text. Returns `(path, is_typeset)`, or `None` when the
    document offers neither — a CSV, or a contract whose extraction failed.

    Cached by content hash under `data/cache/pdf/`, so the second view of a page
    costs a file read. The hash covers the text as well as the URL, so editing a
    document's extraction produces a different cache entry rather than a stale
    page — the same reasoning as the content-addressed Storage keys (issue #20).
    """
    from core.storage import files  # local import: keeps this module usable without Supabase

    is_pdf_source = (file_type or "").lower() == "pdf" or (filename or "").lower().endswith(".pdf")

    if storage_url and is_pdf_source:
        cached = _cache_path("src", storage_url)
        if cached.exists():
            return cached, False
        try:
            data = files.load(storage_url)
        except Exception as exc:
            log.warning("storage load failed for %s: %s", storage_url, exc)
            data = None
        if data:
            _write(cached, data)
            return cached, False
        log.info("no bytes behind %s; falling back to typesetting", storage_url)

    if extracted_text and extracted_text.strip():
        cached = _cache_path("txt", f"{filename}\n{extracted_text}")
        if cached.exists():
            return cached, True
        _write(cached, typeset_pdf(extracted_text, title=filename))
        return cached, True

    return None


def render_document_page(
    *,
    storage_url: str | None,
    extracted_text: str | None,
    filename: str = "",
    file_type: str | None = None,
    page: int | None,
    bbox: list[float] | None,
    dpi: int = DEFAULT_DPI,
) -> tuple[bytes, bool] | None:
    """`(png_bytes, is_typeset)` for one page of one document, highlighted.

    The single entry point both frontends use, so a page cannot look one way in
    Streamlit and another in the FastAPI app. `is_typeset` travels with the image
    because the caller has to *say* so: a page we laid out from the filing's text
    is honest evidence only while it is labelled as one (ADR-021).

    `page=None` renders page 1 — the honest fallback for a clause whose quote was
    never located, where showing the document's first page beats showing nothing.
    """
    source = ensure_pdf(
        storage_url=storage_url,
        extracted_text=extracted_text,
        filename=filename,
        file_type=file_type,
    )
    if source is None:
        return None

    path, is_typeset = source
    image = render_highlighted(path, page or 1, bbox, dpi=dpi)
    if image is None:
        return None
    return image, is_typeset


def _cache_path(kind: str, key: str) -> Path:
    digest = hashlib.sha256(key.encode("utf-8", "replace")).hexdigest()[:16]
    return CACHE_DIR / f"{kind}_{digest}.pdf"


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write-then-rename: two Streamlit reruns racing on the same page must never
    # leave a half-written PDF for the other one to open.
    temporary = path.with_suffix(".part")
    temporary.write_bytes(data)
    temporary.replace(path)
