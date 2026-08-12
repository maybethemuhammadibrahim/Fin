"""[A] Supabase Storage upload/download with signed URLs.

Two backends behind one interface. `backend()` reports which is live:

* **supabase** — when `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` are both set.
  Files go to the private `finsight-documents` bucket and are read back through
  short-lived signed URLs.
* **local** — otherwise. Files go to `data/uploads/<run_id>/`. Fine for offline
  work, **not deployable**: Streamlit Community Cloud has an ephemeral
  filesystem, so uploads would vanish on restart.

**Why the service_role key and not the anon key.** The bucket is private with no
RLS policies, so the anon key gets `403: new row violates row-level security
policy` on upload. The alternatives were to open the bucket to the anon role —
which makes privacy depend on a key designed to be publishable, for documents
that are client contracts — or to use service_role, which bypasses RLS. Streamlit
renders entirely server-side, so the key never reaches a browser. That is the
condition that makes it the right choice; it would be the wrong one in a
client-rendered app.

The key is a secret with full database access. It is never logged, never
returned, and never rendered.
"""

from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
from pathlib import Path

from core.config import PROJECT_ROOT, settings

log = logging.getLogger(__name__)

UPLOAD_ROOT = PROJECT_ROOT / "data" / "uploads"

#: Private bucket, created by hand in the Supabase dashboard.
BUCKET = "finsight-documents"

#: Signed URLs are short-lived on purpose — they end up in `documents.storage_url`,
#: and a row that outlives its URL is better than a URL that outlives the demo.
SIGNED_URL_TTL_SECONDS = 60 * 60


class StorageError(RuntimeError):
    """Raised only by `save_upload`, the one operation that must not fail quietly."""


# ---------------------------------------------------------------------------
# Backend selection
# ---------------------------------------------------------------------------


def backend() -> str:
    """Which storage backend is live: "supabase" or "local"."""
    if settings.supabase_url and settings.supabase_service_key:
        return "supabase"
    return "local"


def is_cloud() -> bool:
    return backend() == "supabase"


def _client():
    """A service_role Supabase client. Built per call — cheap, and the key may
    change between reruns without a restart."""
    from supabase import create_client

    return create_client(settings.supabase_url, settings.supabase_service_key)


def _bucket():
    return _client().storage.from_(BUCKET)


# ---------------------------------------------------------------------------
# Naming
# ---------------------------------------------------------------------------


def safe_filename(name: str) -> str:
    """Strip a filename down to something safe as a path and an object key.

    Uploaded names are user input and arrive with spaces, accents, and
    occasionally path separators.
    """
    stem = Path(name).name  # discards any directory component
    stem = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode()
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem)
    stem = re.sub(r"_+(\.[A-Za-z0-9]+)$", r"\1", stem)  # "v2_.pdf" -> "v2.pdf"
    stem = stem.strip("._")
    return stem or "upload"


def object_key(filename: str, run_id: int, data: bytes) -> str:
    """Where a file lives in the bucket: run-scoped and **content-addressed**.

    `<run_id>/<sha256[:12]>_<safe name>`.

    The hash is not decoration. Supabase serves downloads through a CDN that
    ignores `cache-control` on upload, so re-uploading *different* bytes to the
    same key returns the **old** content for up to an hour — verified: the
    server's object listing showed the new size while `download()` still handed
    back the previous bytes, and a deleted object stayed readable. Phase 4
    uploads a document and immediately extracts text from it, so a stale read
    means extracting the wrong version of a contract.

    Content-addressing removes the failure mode rather than working around it:
    a key's bytes can never change, so a stale cache is always correct. Identical
    content re-uploaded is a genuine no-op that dedupes to the same URL.
    """
    digest = hashlib.sha256(data).hexdigest()[:12]
    return f"{run_id}/{digest}_{safe_filename(filename)}"


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------


def save_upload(data: bytes, filename: str, run_id: int) -> str:
    """Persist an uploaded file and return the URL for its `documents` row.

    Raises `StorageError` on failure rather than returning None: a silently
    dropped upload would leave a `documents` row pointing at nothing, and the
    user would find out at extraction time in Phase 4 instead of now.
    """
    if is_cloud():
        return _save_supabase(data, filename, run_id)
    return _save_local(data, filename, run_id)


def _save_supabase(data: bytes, filename: str, run_id: int) -> str:
    key = object_key(filename, run_id, data)
    try:
        # upsert stays on so re-uploading identical bytes is idempotent rather
        # than a 409. Because the key is content-addressed, an upsert can only
        # ever rewrite a byte-for-byte identical object.
        _bucket().upload(
            key,
            data,
            {"content-type": _content_type(filename), "upsert": "true"},
        )
    except Exception as exc:  # supabase raises StorageApiError and friends
        raise StorageError(f"could not upload {filename!r} to {BUCKET}: {exc}") from exc

    log.info("uploaded %s (%d bytes) to %s", key, len(data), BUCKET)
    return f"supabase://{BUCKET}/{key}"


def _save_local(data: bytes, filename: str, run_id: int) -> str:
    safe = safe_filename(filename)
    target_dir = UPLOAD_ROOT / str(run_id)
    target_dir.mkdir(parents=True, exist_ok=True)

    target = target_dir / safe
    # Never silently overwrite a differently-sourced file with the same name.
    counter = 1
    while target.exists() and target.read_bytes() != data:
        target = target_dir / f"{Path(safe).stem}_{counter}{Path(safe).suffix}"
        counter += 1

    try:
        target.write_bytes(data)
    except OSError as exc:
        raise StorageError(f"could not write {target}: {exc}") from exc

    log.info("saved upload %s (%d bytes) for run %s", target.name, len(data), run_id)
    return target.as_uri()


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


def _file_uri_to_path(storage_url: str) -> Path:
    """`file://` URI -> a real native path, on Windows too.

    `storage_url[len("file://"):]` looks right and is wrong: `Path.as_uri()` on
    Windows produces `file:///C:/Users/...` (three slashes), so a naive strip
    leaves a leading `/` in front of the drive letter (`/C:/Users/...`).
    `WindowsPath` parses that as a folder literally named `C:` under the current
    drive's root, not the C: drive itself, so `is_file()` is always False.
    Found live: `render_pending_csv_mappings` marked every CSV upload
    'failed -- could not read the uploaded file back from storage' on Windows
    (Phase 4) — Phase 2's own verification only exercised the Supabase backend.
    `urllib.request.url2pathname` is the stdlib function that already knows the
    per-platform rule.
    """
    import urllib.parse
    import urllib.request

    return Path(urllib.request.url2pathname(urllib.parse.urlparse(storage_url).path))


def load(storage_url: str) -> bytes | None:
    """Read a stored file back, or None if it is not retrievable.

    Returns None rather than raising. A seeded `seed://` URL has no file behind
    it, a local file may have been cleaned up, and a bucket object may have been
    deleted — in every case the clause viewer must degrade, not crash (ADR-005).
    """
    if storage_url.startswith("supabase://"):
        key = storage_url[len(f"supabase://{BUCKET}/") :]
        try:
            return _bucket().download(key)
        except Exception as exc:
            log.warning("could not download %s: %s", key, exc)
            return None

    if storage_url.startswith("file://"):
        path = _file_uri_to_path(storage_url)
        return path.read_bytes() if path.is_file() else None

    if storage_url.startswith("seed://"):
        return None  # seeded placeholder, no bytes behind it

    log.warning("unsupported storage URL scheme: %s", storage_url[:20])
    return None


def signed_url(storage_url: str, expires_in: int = SIGNED_URL_TTL_SECONDS) -> str | None:
    """A time-limited HTTPS URL for a stored object, or None.

    Only meaningful on the Supabase backend; local files have no URL a browser
    can reach.
    """
    if not storage_url.startswith("supabase://"):
        return None
    key = storage_url[len(f"supabase://{BUCKET}/") :]
    try:
        result = _bucket().create_signed_url(key, expires_in)
    except Exception as exc:
        log.warning("could not sign %s: %s", key, exc)
        return None
    if isinstance(result, dict):
        return result.get("signedURL") or result.get("signedUrl")
    return getattr(result, "signed_url", None)


def delete(storage_url: str) -> bool:
    """Remove a stored object. Returns whether it is now gone."""
    if storage_url.startswith("supabase://"):
        key = storage_url[len(f"supabase://{BUCKET}/") :]
        try:
            _bucket().remove([key])
            return True
        except Exception as exc:
            log.warning("could not delete %s: %s", key, exc)
            return False

    if storage_url.startswith("file://"):
        path = _file_uri_to_path(storage_url)
        path.unlink(missing_ok=True)
        return not path.exists()

    return False


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------


def check() -> tuple[bool, str]:
    """(ok, message) for the health page. Never raises."""
    if not is_cloud():
        missing = []
        if not settings.supabase_url:
            missing.append("SUPABASE_URL")
        if not settings.supabase_service_key:
            missing.append("SUPABASE_SERVICE_KEY")
        return False, f"local disk — {' and '.join(missing)} not set" if missing else "local disk"
    try:
        _bucket().list()
        return True, f"Supabase Storage · bucket `{BUCKET}`"
    except Exception as exc:
        return False, f"bucket `{BUCKET}` unreachable: {type(exc).__name__}: {exc}"


def describe() -> str:
    """One line for the UI about where uploads go."""
    if is_cloud():
        return f"Supabase Storage · private bucket `{BUCKET}`"
    return f"local disk · `{UPLOAD_ROOT.relative_to(PROJECT_ROOT)}/` (not deployable)"


def _content_type(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    return {
        ".pdf": "application/pdf",
        ".csv": "text/csv",
        ".txt": "text/plain",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }.get(suffix, "application/octet-stream")


__all__ = [
    "BUCKET",
    "StorageError",
    "backend",
    "check",
    "delete",
    "describe",
    "is_cloud",
    "load",
    "object_key",
    "safe_filename",
    "save_upload",
    "signed_url",
]
