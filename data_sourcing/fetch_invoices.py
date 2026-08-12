"""[B] Download invoice and receipt corpora from HuggingFace, plus a Kaggle
bank-transaction dataset for realistic description strings. Phase 3.

Bounded on purpose: OCR is a Phase 4 FALLBACK branch, never the critical path (ADR-001
note in implementation_plan.md — CUAD/EDGAR contracts and CSV actuals are all digital-
text, so the primary pipeline never touches these). `limit` keeps every fetch to a
sample instead of pulling multi-GB datasets that nothing downstream needs yet.

Kaggle requires credentials (`~/.kaggle/kaggle.json` or `KAGGLE_USERNAME`/`KAGGLE_KEY`)
that are not part of this project's env vars (core/config.py) and are unverified per
docs/state.json known_issues #7. `fetch_kaggle_transactions` degrades to returning None
rather than raising, so scenario_builder.py's own synthetic noise generator is always a
safe fallback — see its docstring.
"""

from __future__ import annotations

import json
from pathlib import Path


def fetch_invoice_images(limit: int = 20, out_dir: str = "data/corpus/invoices") -> list[Path]:
    """`mychen76/invoices-and-receipts_ocr_v1` — invoice images + OCR + parsed JSON.
    The scanned-invoice path (Phase 4 fallback, Phase 7 OCR demo)."""
    from datasets import load_dataset

    out = Path(out_dir) / "mychen76"
    out.mkdir(parents=True, exist_ok=True)
    ds = load_dataset("mychen76/invoices-and-receipts_ocr_v1", split="train", streaming=True)

    paths: list[Path] = []
    for i, row in enumerate(ds):
        if i >= limit:
            break
        img = row.get("image")
        if img is None:
            continue
        img_path = out / f"invoice_{i:03d}.png"
        img.save(img_path)
        paths.append(img_path)
        parsed = row.get("parsed_data") or row.get("raw_data")
        if parsed is not None:
            (out / f"invoice_{i:03d}.json").write_text(json.dumps(parsed, default=str), encoding="utf-8")
    return paths


def fetch_invoice_ocr_ground_truth(limit: int = 20, out_dir: str = "data/corpus/invoices") -> list[Path]:
    """CORD (`naver-clova-ix/cord-v2`) — receipt OCR with bounding-box ground truth.
    Validates the OCR path independent of FinSight's own extraction code."""
    from datasets import load_dataset

    out = Path(out_dir) / "cord"
    out.mkdir(parents=True, exist_ok=True)
    ds = load_dataset("naver-clova-ix/cord-v2", split="train", streaming=True)

    paths: list[Path] = []
    for i, row in enumerate(ds):
        if i >= limit:
            break
        img = row.get("image")
        if img is None:
            continue
        img_path = out / f"receipt_{i:03d}.png"
        img.save(img_path)
        paths.append(img_path)
        gt = row.get("ground_truth")
        if gt is not None:
            (out / f"receipt_{i:03d}.json").write_text(str(gt), encoding="utf-8")
    return paths


def fetch_kaggle_transactions(out_dir: str = "data/corpus/invoices/kaggle_txns") -> Path | None:
    """A Kaggle bank-transaction dataset, for realistic description strings and amount
    distributions that scenario_builder.py can sample noise from.

    Returns None (never raises) when kagglehub is unavailable or Kaggle credentials are
    not configured — this is a nice-to-have for scenario realism, not a hard dependency;
    scenario_builder.py's own synthetic noise generator covers the same need."""
    try:
        import kagglehub
    except ImportError:
        return None

    try:
        path = kagglehub.dataset_download("computingvictor/transactions-fraud-datasets")
    except Exception:
        return None

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    return Path(path)
