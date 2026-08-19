"""[B] Accepting an uploaded file: save it, record it, read it. Phase 12.

**Why this module exists.** Every step of taking an upload was already
framework-free — `core/storage/files.py` saves it, `core/extraction/` reads it,
`core/extraction/csv_parser.py` parses it — but the code that *ordered* those
steps lived inside `app/components/file_uploader.py`, wrapped in `st.` calls. So
the second frontend could not upload anything without either importing Streamlit
or reimplementing the sequence, and a reimplementation is how two frontends come
to disagree about what a document's status means.

This is that sequence, with nothing drawn. Both frontends call it and neither
owns it:

    app/components/file_uploader.py   Streamlit widgets  ->  ingest_files()
    web/routers/uploads.py            an HTML form       ->  ingest_files()

Nothing here imports `streamlit`, `fastapi` or any template engine, and nothing
here raises at the caller: a file that cannot be saved or cannot be read comes
back as a row in the result with a readable reason, because both callers need to
show that reason rather than crash on it.

**The two-step CSV rule (ADR-010) lives here too.** A statement is *not* parsed
on upload. It lands at `extraction_status='pending'` and stays there until a
human has confirmed which column is the date and which is the amount, through
`propose_mapping` then `apply_mapping`. That split is the reason this module has
two entry points instead of one, and it is not negotiable: parsing money out of
a column nobody looked at is how a run silently fills with wrong figures.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db.models import ActualTransaction, ColumnMapping, Document
from core.extraction import csv_parser
from core.extraction import document_router as router
from core.extraction.csv_parser import REQUIRED_FIELDS, ColumnProposal
from core.storage import files

#: Only offer what `document_router.detect_type()` can actually route. This list
#: has been wrong twice in the same way, so the rule is worth stating: **an
#: extension goes in here only once something can read it.** "docx" was removed
#: on 2026-08-17 and "xlsx" on 2026-08-19; both were advertised for months and
#: both failed every time with "unsupported file type", which reads to a user as
#: a broken app rather than an unbuilt feature.
#:
#: ".txt" is genuinely supported — it is the shape the EDGAR corpus arrives in.
#: A spreadsheet exported as .csv works today.
CONTRACT_TYPES = ["pdf", "txt"]
ACTUALS_TYPES = ["csv", "pdf", "png", "jpg", "jpeg"]

#: What the three categories mean, since `documents.category` is a bare string.
CATEGORIES = ("contract", "statement", "invoice")


# ---------------------------------------------------------------------------
# Which path an upload takes
# ---------------------------------------------------------------------------


def actuals_category(filename: str) -> str:
    """Which path an actuals upload takes, decided by its extension.

    `statement` means "hold this at `pending` until a human confirms its column
    mapping" (ADR-010); `invoice` means "extract the text now". That is a fact
    about the file, and the filename already states it.

    **Until 2026-08-19 a radio button decided this instead, and getting it wrong
    was silent.** A .csv dropped while the toggle read "Scanned image or PDF"
    was tagged `invoice`, so it skipped the column-mapping step entirely — the
    only thing that ever writes `actual_transactions` — and landed as
    `extraction_status='complete'`, a green tick in the document list, with
    **zero transactions imported**. Reconciliation then compares a full expected
    timeline against no payments at all and reports every billing as a ghost
    invoice. A wrong number on screen is bad; a confident tick over money that
    never arrived is worse, because nothing looks broken.

    The toggle is gone rather than fixed: it asked the user to restate what the
    filename says. A .pdf tagged `statement` was a dead end too — the mapping
    step parses only .csv, so it could only ever end as `failed`.
    """
    return "statement" if Path(filename).suffix.lower() == ".csv" else "invoice"


# ---------------------------------------------------------------------------
# Reading a file
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExtractionOutcome:
    """What reading one uploaded file produced. Never an exception."""

    status: str  # "complete" | "failed"
    error: str | None = None
    text: str | None = None
    page_count: int | None = None


def extract_upload(data: bytes, filename: str) -> ExtractionOutcome:
    """Read one upload's text, or say why not.

    Writes to a temp file because `document_router.extract()` takes a path —
    pdfplumber and pymupdf both need one — and the bytes are already in hand, so
    this never round-trips through storage.

    Never raises. An unsupported type, a corrupt PDF and a scan with no text
    layer all come back as `status="failed"` with a sentence that names the
    actual problem, because that sentence is what the user is shown.
    """
    suffix = Path(filename).suffix or ".bin"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name
    try:
        try:
            doc = router.extract(tmp_path)
        except ValueError as exc:
            # Unsupported extension, or a file that claims an extension it
            # cannot honour (a .pdf that will not open reports the same way).
            return ExtractionOutcome(status="failed", error=str(exc))
        if not doc.full_text.strip():
            reason = "; ".join(doc.warnings) or "no extractable text"
            return ExtractionOutcome(status="failed", error=reason)
        return ExtractionOutcome(
            status="complete", text=doc.full_text, page_count=doc.page_count
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Recording an upload
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IngestedFile:
    """One file's fate. `document_id` is None only when nothing was recorded."""

    filename: str
    status: str  # "complete" | "failed" | "pending" | "skipped"
    document_id: int | None = None
    error: str | None = None

    @property
    def needs_columns(self) -> bool:
        """True for a statement waiting on ADR-010's confirmation step."""
        return self.status == "pending"


@dataclass(frozen=True)
class IngestResult:
    files: list[IngestedFile] = field(default_factory=list)

    @property
    def recorded(self) -> int:
        """How many new `documents` rows exist because of this call."""
        return sum(1 for f in self.files if f.status != "skipped")

    @property
    def pending(self) -> list[IngestedFile]:
        return [f for f in self.files if f.needs_columns]

    @property
    def failed(self) -> list[IngestedFile]:
        return [f for f in self.files if f.status == "failed"]


def ingest_files(
    session: Session,
    run_id: int,
    uploads: Sequence[tuple[str, bytes]],
    category: str,
) -> IngestResult:
    """Save, record and (where appropriate) read a batch of uploads.

    `uploads` is `(filename, bytes)` so neither a Streamlit `UploadedFile` nor a
    Starlette `UploadFile` leaks into this layer.

    A file whose name is already in this run is skipped rather than duplicated —
    Streamlit re-delivers its whole selection on every rerun, and a browser form
    re-posts on refresh, so both callers need this and neither should own it.

    Nothing is committed here; the caller's session scope decides that.
    """
    if not uploads:
        return IngestResult()

    existing = {
        name
        for (name,) in session.execute(
            select(Document.filename).where(Document.run_id == run_id)
        ).all()
    }

    results: list[IngestedFile] = []
    for filename, data in uploads:
        if filename in existing:
            results.append(IngestedFile(filename, status="skipped"))
            continue

        try:
            url = files.save_upload(data, filename, run_id)
        except files.StorageError as exc:
            # Loud, not silent: a dropped upload would otherwise leave a
            # documents row pointing at nothing, found only at extraction time.
            results.append(IngestedFile(filename, status="failed", error=str(exc)))
            continue

        kwargs: dict = dict(
            run_id=run_id,
            filename=filename,
            file_type=filename.rsplit(".", 1)[-1].lower() if "." in filename else None,
            category=category,
            storage_url=url,
        )
        if category == "statement":
            # ADR-010. Not read at all until a human confirms its columns.
            kwargs["extraction_status"] = "pending"
            outcome = ExtractionOutcome(status="pending")
        else:
            outcome = extract_upload(data, filename)
            kwargs.update(
                extraction_status=outcome.status,
                error_message=outcome.error,
                extracted_text=outcome.text,
                extracted_page_count=outcome.page_count,
            )

        document = Document(**kwargs)
        session.add(document)
        session.flush()  # so document.id is available to the caller
        existing.add(filename)
        results.append(
            IngestedFile(
                filename,
                status=outcome.status,
                document_id=document.id,
                error=outcome.error,
            )
        )

    return IngestResult(results)


def split_actuals(uploads: Sequence[tuple[str, bytes]]) -> tuple[list, list]:
    """`(statements, invoices)` — the actuals zone's two paths, by extension."""
    statements = [u for u in uploads if actuals_category(u[0]) == "statement"]
    invoices = [u for u in uploads if actuals_category(u[0]) == "invoice"]
    return statements, invoices


# ---------------------------------------------------------------------------
# The CSV column mapping (ADR-010): propose, then apply
# ---------------------------------------------------------------------------


def cached_mapping(session: Session, header_signature: str) -> dict[str, str] | None:
    """A mapping already confirmed for this exact header layout, if any."""
    row = session.scalars(
        select(ColumnMapping).where(ColumnMapping.header_signature == header_signature)
    ).first()
    return row.mapping if row else None


@dataclass(frozen=True)
class MappingProposal:
    """What to show a human before any amount is parsed."""

    proposal: ColumnProposal
    columns: list[str]
    #: Set when this exact header layout was confirmed before, so the caller can
    #: apply it without asking again.
    cached: dict[str, str] | None = None

    @property
    def signature(self) -> str:
        return self.proposal.header_signature

    @property
    def suggested(self) -> dict[str, str]:
        return self.cached or self.proposal.mapping


def propose_mapping(session: Session, document: Document) -> MappingProposal | None:
    """Read a pending statement back out of storage and propose its columns.

    Returns None when the file cannot be read back at all — the caller records
    that against the document rather than showing an empty mapper.
    """
    data = files.load(document.storage_url)
    if data is None:
        return None

    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name
    try:
        proposal = csv_parser.sniff_columns(tmp_path)
    except Exception:  # noqa: BLE001 - an unreadable CSV is the caller's to report
        return None
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    columns = (
        list(proposal.sample_rows[0].keys())
        if proposal.sample_rows
        else list(proposal.mapping.values())
    )
    return MappingProposal(
        proposal=proposal,
        columns=columns,
        cached=cached_mapping(session, proposal.header_signature),
    )


def missing_fields(mapping: dict[str, str]) -> list[str]:
    """Which required fields a proposed mapping still lacks.

    `description` is optional — plenty of bank exports have no usable one, and a
    transaction with a date and an amount is still reconcilable. Date and amount
    are not: without them there is nothing to compare.
    """
    return [f for f in ("date", "amount") if not mapping.get(f)]


@dataclass(frozen=True)
class MappingOutcome:
    status: str  # "complete" | "failed"
    transactions: int = 0
    error: str | None = None


def apply_mapping(
    session: Session, document: Document, mapping: dict[str, str]
) -> MappingOutcome:
    """Parse a confirmed statement into `actual_transactions`.

    This is the only function in the project that turns a bank export into money
    rows, and it is reached only from a human confirmation (ADR-010). It also
    remembers the mapping against the header signature, so the same export shape
    never has to be confirmed twice.

    A mapping that parses nothing leaves the document `failed` rather than
    `complete`: an empty import that reported success would look exactly like a
    client who paid nothing all year.
    """
    if missing_fields(mapping):
        return MappingOutcome(
            status="failed",
            error=f"map at least date and amount (missing: {', '.join(missing_fields(mapping))})",
        )

    data = files.load(document.storage_url)
    if data is None:
        document.extraction_status = "failed"
        document.error_message = "could not read the uploaded file back from storage"
        return MappingOutcome(status="failed", error=document.error_message)

    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name
    try:
        rows = csv_parser.parse_transactions(tmp_path, mapping)
        signature = csv_parser.sniff_columns(tmp_path).header_signature
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    if not rows:
        document.extraction_status = "failed"
        document.error_message = "no rows could be parsed with the confirmed mapping"
        return MappingOutcome(status="failed", error=document.error_message)

    for row in rows:
        session.add(
            ActualTransaction(
                run_id=document.run_id,
                document_id=document.id,
                client_id=None,  # resolved later by the client matcher
                transaction_date=row.transaction_date,
                amount=row.amount,
                description=row.description,
                source_type="bank",
            )
        )

    if cached_mapping(session, signature) is None:
        session.add(ColumnMapping(header_signature=signature, mapping=mapping))

    document.extraction_status = "complete"
    document.error_message = None
    document.extracted_text = (
        f"{len(rows)} transaction(s) parsed from columns: {', '.join(mapping.values())}"
    )
    session.flush()
    return MappingOutcome(status="complete", transactions=len(rows))


__all__ = [
    "ACTUALS_TYPES",
    "CATEGORIES",
    "CONTRACT_TYPES",
    "REQUIRED_FIELDS",
    "ExtractionOutcome",
    "IngestResult",
    "IngestedFile",
    "MappingOutcome",
    "MappingProposal",
    "actuals_category",
    "apply_mapping",
    "cached_mapping",
    "extract_upload",
    "ingest_files",
    "missing_fields",
    "propose_mapping",
    "split_actuals",
]
