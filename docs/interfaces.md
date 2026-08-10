# INTERFACES — The Contract Between User A and User B

> **This file is written BEFORE the code, not after.**
> When a phase needs a function that crosses the A/B boundary, the signature goes here first. The other person then writes against it immediately using a stub, without waiting for the real implementation.
>
> **Changing a signature that already appears here requires telling the other person.** Silently changing it is the single fastest way to break each other's work.

**Status:** Phases 0, 1 and 2 complete and marked ✅; everything from Phase 3 down is still the *planned* contract. Mark each `✅` as it lands.

---

## Conventions

- **Money** is always `float`, always in the run's base currency, always rounded to 2dp at the boundary.
- **Dates** are always `datetime.date`, never strings, never `datetime`.
- **IDs** are always `int` primary keys from the database.
- Every function that touches the DB takes `session: Session` as its **first** argument.
- Every function that produces run-scoped data takes `run_id: int`.
- Functions return **Pydantic models or dataclasses**, never bare dicts, so the other side gets autocomplete and type errors instead of `KeyError` at runtime.
- A function that can legitimately fail returns `None` — it does not raise. Callers must handle `None`.

---

## Shared data shapes

Defined in `core/ai/schemas.py` [A] and imported by everyone.

```python
# ---- Contract extraction output ----
class Escalation(BaseModel):
    percentage: float
    after_months: int
    clause_text: str                 # VERBATIM from the document. Never paraphrased.

class Discount(BaseModel):
    percentage: float
    duration_months: int
    clause_text: str

class Milestone(BaseModel):
    description: str
    amount: float
    due_condition: str | None
    clause_text: str

class ContractRules(BaseModel):
    client_name: str
    contract_start_date: date | None
    contract_end_date: date | None
    base_amount: float | None
    currency: str = "USD"
    billing_frequency: Literal["monthly","quarterly","annual","one_time","unknown"]
    payment_terms: str | None
    escalation: Escalation | None
    discounts: list[Discount] = []
    milestones: list[Milestone] = []

# ---- Everything downstream ----
class TimelineEntry(BaseModel):
    client_id: int
    contract_rule_id: int
    billing_date: date
    expected_amount: float
    payment_type: Literal["recurring","milestone"]
    applied_escalation: bool
    applied_discount_pct: float
    source_clause_ref_id: int | None
    notes: str

class Anomaly(BaseModel):
    anomaly_type: Literal["ghost_invoice","forgotten_raise","zombie_discount","short_change"]
    client_id: int
    expected_timeline_id: int
    actual_transaction_id: int | None
    clause_reference_id: int | None
    expected_amount: float
    actual_amount: float
    gap: float
    billing_date: date
    confidence_score: float          # 0.0 - 1.0, from the rule engine
    status: Literal["unverified","confirmed","false_positive","needs_review"]

class ClauseLocation(BaseModel):
    page: int
    bbox: list[float]                # [x0, y0, x1, y1] in PDF points
    method: Literal["exact","fuzzy"]
```

---

## Phase 0 — Configuration

Everything reads configuration through this module. **Nothing else in the project touches `os.environ`.**

```python
# core/config.py                                               [B]  ✅

settings: Settings          # the module-level object everyone imports

def get_settings() -> Settings:
    """Resolved once per process (lru_cache).
       environment -> .env -> st.secrets -> declared default."""

def mask(value: str, head: int = 4, tail: int = 4) -> str:
    """'AIzaSyDxxxx4f2a' -> 'AIza...4f2a'. Never log a raw secret."""

def configure_logging(level: str | None = None) -> None:
    """Apply LOG_LEVEL once, at process start."""

class ConfigError(RuntimeError): ...

class Settings:                         # frozen dataclass
    database_url: str | None            # None -> SQLite fallback
    supabase_url: str | None
    supabase_key: str | None
    llm_provider: str                   # colab_tunnel | kaggle_tunnel | custom
    llm_model: str                      # base weights now, tuned name from Phase 10
    colab_tunnel_url: str | None
    kaggle_tunnel_url: str | None
    custom_base_url: str | None
    llm_api_key: str | None             # shared secret; the tunnel is PUBLIC
    llm_timeout_seconds: int            # default 120 — cold starts are slow
    hf_token: str | None
    llm_cache_enabled: bool
    log_level: str

    def validate(self) -> None:
        """Raises ConfigError naming EVERY missing required variable at once.
           Only the ACTIVE endpoint's URL is required."""

    @property
    def resolved_database_url(self) -> str:
        """What Phase 1's database.py connects to. Never None."""

    @property
    def using_sqlite_fallback(self) -> bool: ...

    @property
    def api_base(self) -> str | None:
        """Normalised base URL for the active endpoint: no trailing slash, no
           /v1 suffix. llm_client appends /v1/chat/completions itself.
           Tolerates the shapes people actually paste after a restart."""

    @property
    def active_base_url(self) -> str | None:
        """The raw value, before normalisation."""

    @property
    def active_endpoint_name(self) -> str:
        """Which env var holds it — for error messages."""

    def checks(self) -> list[Setting]:
        """Every variable with .status ✅/❌/⚪ and .display (masked if secret).
           Drives B's config page; A may use it in scripts to fail early."""
```

**Contract notes.** `validate()` is the only thing that raises; every other member is safe to read. It reports *all* problems at once, not the first. A missing optional variable is never an error — `DATABASE_URL` unset is a legitimate offline mode, not a failure.

> **Amended 2026-07-29 by ADR-011.** The provider fields used to be `gemini_api_key` / `groq_api_key` / `openrouter_api_key` / `finetuned_tunnel_url`. **No frontier model API is called anywhere in this project.** The endpoints are now our own Colab/Kaggle notebook sessions, and their URLs change on every restart — so `api_base` must be read at call time, never captured at import.

---

## Phase 1 — Database

```python
# core/db/models.py                                            [A]  ✅
#   12 models: Run, Document, Client, ContractRule, ClauseReference,
#   PriceEscalation, Discount, Milestone, ExpectedTimeline,
#   ActualTransaction, Anomaly, ColumnMapping.
#   ALL_MODELS is the canonical tuple, in dependency order.
Base: DeclarativeBase
ALL_MODELS: tuple[type[Base], ...]
ANOMALY_TYPES / ANOMALY_STATUSES / LOCATE_METHODS / PAYMENT_TYPES
BILLING_FREQUENCIES / EXTRACTION_STATUSES   # allowed values, enforced by CheckConstraint

# core/db/database.py                                          [A]  ✅
def get_engine() -> Engine: ...            # lazy; import never opens a socket
def get_session() -> Session: ...          # caller closes
def session_scope() -> Iterator[Session]:  # contextmanager: commits/rolls back/closes
def init_db() -> None: ...                 # create_all, idempotent
def drop_all() -> None: ...                # destructive; init_db.py --drop only
def check_connection() -> tuple[bool, str] # never raises
def describe_backend() -> str              # password stripped, safe to display
def reset_engine() -> None                 # tests that swap DATABASE_URL

# core/db/queries.py                                           [B]  ✅
def create_run(session, label: str) -> int: ...
def list_runs(session) -> list[RunRow]: ...
def get_latest_run(session) -> RunRow | None: ...
def get_summary_stats(session, run_id: int) -> SummaryStats: ...
def list_anomalies(session, run_id: int, status: str | None = None,
                   anomaly_type: str | None = None) -> list[AnomalyRow]: ...
def get_anomaly(session, anomaly_id: int) -> AnomalyRow | None: ...
def get_clause_reference(session, clause_ref_id: int) -> ClauseRefRow | None: ...
def list_clients(session, run_id: int) -> list[ClientRow]: ...
def get_document(session, document_id: int) -> DocumentRow | None: ...
def list_documents(session, run_id: int) -> list[DocumentRow]: ...
def table_counts(session, run_id: int | None = None) -> dict[str, int]: ...
def list_transactions(session, run_id: int,
                      client_id: int | None = None) -> list[ActualTransaction]: ...
```

**Row shapes** — frozen dataclasses defined in `queries.py`, not ORM objects.
Streamlit reruns the script on every interaction, and a detached ORM instance
raises `DetachedInstanceError` the moment a lazy relationship is touched after
its session closed. Plain data cannot.

```python
SummaryStats(run_id, total_leaked, anomaly_count, client_count, document_count,
             by_type: dict[str,int], unverified_count, ungrounded_count)
             .grounded_count
AnomalyRow(id, run_id, client_id, client_name, anomaly_type, expected_amount,
           actual_amount, gap, confidence_score, status, billing_date,
           clause_reference_id, expected_timeline_id, actual_transaction_id,
           agent_reasoning, verified_at).has_clause
ClauseRefRow(id, contract_rule_id, document_id, clause_type, clause_text,
             source_page, source_bbox, locate_method, document_filename)
             .is_grounded          # False is NORMAL (ADR-005), not an error
ClientRow(id, run_id, name, normalized_name, contract_count)
DocumentRow(id, run_id, filename, file_type, category, storage_url,
            extraction_status, error_message, uploaded_at)
RunRow(id, label, llm_provider, model_name, created_at)
```

> **⚠️ Signature changed 2026-08-08 — `list_anomalies` returns `list[AnomalyRow]`, not `list[Anomaly]`.**
> `Anomaly` is already the ORM model *and* the Phase-5 Pydantic schema in `core/ai/schemas.py`. Three
> different things cannot share one name. The DB row also carries `id`, `status`, `client_name` and the
> agent's output, which the Phase-5 schema does not, while the schema carries `billing_date`, which lives
> on `expected_timeline`. Phase 5 keeps its `Anomaly` schema unchanged; the query layer returns rows.

> **Two additions Phase 1 made to the plan's schema.** A **`milestones`** table — the ER diagram draws 11
> tables while the plan text and the `models.py` stub both say 12, and milestones are the missing one
> (`ContractRules.milestones` exists above, `TimelineEntry.payment_type` includes `"milestone"`).
> And **`expected_timeline.source_clause_ref_id`**, which `TimelineEntry` in this file already declared
> but the ER diagram omitted — without it an anomaly cannot inherit the clause that proves it.

---

## Phase 2 — Seeding & UI

```python
# scripts/seed_demo.py                                         [A]  ✅
def seed_run(session, scenario_dir: str | None = None,
             label: str = "demo_v1") -> int:
    """Writes a complete, internally consistent run into every table the UI
       reads. Returns run_id. scenario_dir raises NotImplementedError until
       Phase 3 builds scenarios on disk — omit it for the built-in demo."""

# core/storage/files.py                                        [A]  ✅ (Supabase backend live)
BUCKET = "finsight-documents"           # private, no RLS policies
class StorageError(RuntimeError): ...
def save_upload(data: bytes, filename: str, run_id: int) -> str   # raises StorageError
def load(storage_url: str) -> bytes | None                        # None, never raises
def signed_url(storage_url: str, expires_in: int = 3600) -> str | None
def delete(storage_url: str) -> bool
def check() -> tuple[bool, str]         # for the health page; never raises
def backend() -> str                    # "supabase" when URL + SERVICE_KEY set, else "local"
def is_cloud() -> bool
def describe() -> str                   # one line for the UI
def safe_filename(name: str) -> str
def object_key(filename: str, run_id: int, data: bytes) -> str
    """<run_id>/<sha256(data)[:12]>_<safe name>"""

# app/state.py                                                 [B]  ✅
def db() -> Iterator[Session]                # contextmanager, one per render
def get_run_id() -> int | None               # defaults to the newest run
def set_run_id(run_id: int | None) -> None
def render_run_selector(label="Run") -> int | None
def get_selected_anomaly() -> int | None
def set_selected_anomaly(anomaly_id: int | None) -> None
def clear_selected_anomaly() -> None

# app/components/summary_cards.py                              [B]  ✅
LEAK_TYPES: dict[str, tuple[str, str]]       # type -> (emoji, label)
def money(amount: float) -> str
def render_summary_cards(stats: SummaryStats) -> None
def render_type_breakdown(stats: SummaryStats) -> None
def render_grounding_note(stats: SummaryStats) -> None

# app/components/anomaly_table.py                              [B]  ✅
def render_anomaly_table(anomalies: list[AnomalyRow]) -> int | None
    """Returns the anomaly_id of the clicked row, or None."""
def render_filters(anomalies: list[AnomalyRow]) -> tuple[str | None, str | None]
def render_anomaly_detail(anomaly: AnomalyRow) -> None
def type_label(anomaly_type: str) -> str

# app/components/clause_viewer.py                              [B]  ✅ (placeholder until Phase 7)
def render_clause_viewer(clause: ClauseRefRow | None) -> None
def render_placeholder() -> None

# app/components/client_confirm.py                             [B]  ✅ (display only until Phase 5)
def render_client_confirm(clients: list[ClientRow]) -> bool   # True when confirmed

# app/components/file_uploader.py                              [B]  ✅
def render_file_uploaders(session, run_id: int) -> int        # count of new documents
def render_document_list(documents: list[DocumentRow]) -> None

# app/components/cash_flow_chart.py                            [B]  ✅ (real series from Phase 9)
def render_cash_flow_chart(baseline: list[float], recovered: list[float],
                           labels: list[str] | None = None,
                           threshold: float | None = None,
                           threshold_label: str = "Cost of the hire") -> None
def render_breakdown(rows: list[tuple[str, float]]) -> None

# app/components/column_mapper.py                              [B]  ⬜ Phase 4
```

> **⚠️ `render_clause_viewer` takes a `ClauseRefRow | None`, not a `clause_ref_id: int`.**
> The page already holds an open session and has to handle "this finding has no clause" anyway
> (hard rule 5), so passing the row keeps the component free of database access and makes the
> None case explicit in the type. Phase 7 adds the rendered page image behind the same signature.

> **⚠️ `render_anomaly_table` takes `list[AnomalyRow]`** — same rename as `list_anomalies`, see Phase 1.

> **⚠️ Object keys are content-addressed, and `object_key` takes the bytes.** Supabase's CDN ignores
> `cache-control`: re-uploading different bytes to the same key returns the **old** content for up to an
> hour, and a deleted object stays readable. Verified against the live bucket. Hashing the content into
> the key makes a key's bytes immutable, so a stale cache is always correct. **Never construct a bucket
> key by hand** — a `documents.storage_url` is the only valid handle to a stored file.

**Two `SummaryStats` fields were added in Phase 2** because the UI must not compute figures:
`affected_client_count` (the "3 of 5" card) and the split of the old `ungrounded_count` into
`unlinked_count` (no clause at all — unproven, hard rule 5) and `unlocatable_count` (clause quoted
but not locatable — valid finding, degraded highlight, ADR-005). `grounding_rate` derives from them.

---

## Phase 3 — Data sourcing

```python
# data_sourcing/fetch_contracts.py                             [A]  ⬜
#   ADR-013: EDGAR is PRIMARY, CUAD is secondary. Reverse of the plan's ordering.
def fetch_edgar_msa(count: int, out_dir: str) -> list[Path]:
    """SEC full-text search, aimed at master/professional services agreements.
       Requires a contact address in the User-Agent; 10 req/s ceiling.
       Measured yield: ~17.7% carry a real amount AND a real escalation."""
def fetch_cuad(limit: int = 200, out_dir: str = "data/corpus/contracts") -> list[Path]:
    """Use HF `theatticusproject/cuad` — public, no token, real PDFs.
       NOT the plan's dvgodoy mirror. Demoted by ADR-013 to Phase 5
       extraction dev and Phase 10 volume; yields ~1.6% usable scenarios."""

def filter_service_contracts(paths: list[Path]) -> list[Path]:
    """Keep on CONCRETE UNREDACTED VALUES, not keyword presence (ADR-013).
       The plan's ANY-keyword KEEP list gives 48.6% retention and 1.6% usable.
       NEVER include bare `escalat` — 68 of its 81 CUAD matches are the
       dispute-escalation procedure. Port the patterns from
       scripts/contract_scoring.py, which is measured."""

def deduplicate(paths: list[Path]) -> list[Path]:
    """One document per filer AND per distinct clause fingerprint.
       Counting documents overstates the corpus ~2.5x: 51 EDGAR 'gold'
       documents carry only 21 distinct clauses. Near-duplicates either side
       of a train/test split silently invalidate Phase 11."""

# scripts/fill_blanks.py  (spike; fold into data_sourcing at Phase 3)  [A]  ✅
def fill_document(text: str, row: dict, rng: Random) -> tuple[str, list[dict]]:
    """Substitute redacted values INTO the contract text, deterministically,
       recording each as ground truth by construction (ADR-014). Returns None
       for any blank whose type cannot be read — refusing beats guessing."""

# data_sourcing/scenario_builder.py                            [B]  ⬜
def build_scenario(contract_paths: list[Path],
                   rules: list[ContractRules],
                   plant: list[str],
                   out_dir: str) -> ScenarioManifest:
    """Derives actuals from TRUE rules, then plants the named anomaly types.
       Writes actuals.csv + ground_truth.json + manifest.json."""
```

---

## Phase 4 — Text extraction

```python
# core/extraction/document_router.py                           [A]  ⬜
def detect_type(file_path: str) -> Literal["text_pdf","scanned","image","csv"]: ...
def extract(file_path: str) -> ExtractedDoc:
    """Single entry point. Routes internally. ExtractedDoc.blocks is a list of
       {page_number, text, is_table}."""

# core/extraction/csv_parser.py                                [B]  ⬜
def sniff_columns(file_path: str) -> ColumnProposal:
    """Reads header + 3 rows, asks the LLM to map them. Human confirms in UI."""
def parse_transactions(file_path: str, mapping: dict) -> list[TransactionRow]: ...

# core/extraction/ocr_cloud.py                                 [B]  ⬜
def ocr_page(image_bytes: bytes) -> str: ...
```

---

## Phase 5 — LLM extraction

```python
# training/serve_model.py   (runs IN Colab/Kaggle, not in the repo runtime) [B] ⬜
#   Stood up FIRST in Phase 5 with BASE Qwen 2.5 3B Instruct (ADR-012).
#   FastAPI + Cloudflare tunnel exposing OpenAI-compatible
#   /v1/chat/completions, bearer-authed against LLM_API_KEY.
#   Phase 10 loads the QLoRA adapter and serves it under a second model name;
#   llm_client.py needs zero changes for either.

# core/ai/llm_client.py                                        [B]  ⬜
def complete(prompt: str, system: str = "", **kw) -> str: ...
def complete_json(prompt: str, schema: type[BaseModel],
                  system: str = "", max_repairs: int = 1) -> BaseModel | None:
    """JSON mode -> Pydantic validate -> one repair retry -> None on failure.
       Endpoint chosen by LLM_PROVIDER; it is always OUR self-hosted model
       (ADR-011). NEVER raises to the caller.

       Self-hosting obligations, all three required:
       - read settings.api_base at CALL time (the tunnel URL rotates)
       - settings.llm_timeout_seconds, plus ONE retry for cold starts
       - return None on an unreachable endpoint, so the UI can say
         'model endpoint is down' instead of rendering a blank result"""

def health() -> bool:
    """Is the endpoint answering? Used by the UI to distinguish 'no anomalies'
       from 'the notebook died'."""

# core/ai/contract_extractor.py                                [A]  ⬜
def extract_rules(doc: ExtractedDoc) -> ContractRules | None: ...

# core/extraction/clause_locator.py                            [A]  ⬜
def locate_clause(pdf_path: str, clause_text: str) -> ClauseLocation | None:
    """exact -> fuzzy -> None. None means the model likely hallucinated the quote."""

# core/ai/client_matcher.py                                    [A]  ⬜
def group_clients(names: list[str], threshold: int = 85) -> dict[str, list[str]]: ...
```

---

## Phase 6 — Timeline & reconciliation

```python
# core/engine/timeline_generator.py                            [A]  ⬜
def generate_timeline(rules: ContractRules,
                      client_id: int,
                      contract_rule_id: int) -> list[TimelineEntry]:
    """PURE FUNCTION. No DB, no network, no LLM. Fully unit-testable."""

# core/engine/reconciliation.py                                [B]  ⬜
def reconcile(expected: list[TimelineEntry],
              actuals: list[TransactionRow],
              date_tolerance_days: int = 15) -> list[Anomaly]:
    """PURE FUNCTION. Aggregates actuals per client-month (see ADR-006)."""

# core/engine/anomaly_classifier.py                            [B]  ⬜
def classify(expected: TimelineEntry, actual: TransactionRow | None,
             rules: ContractRules) -> tuple[str, float]:
    """Returns (anomaly_type, confidence_score)."""
```

---

## Phase 7 — Clause viewer

```python
# core/extraction/pdf_renderer.py                              [B]  ⬜
def render_highlighted(pdf_path: str, page: int,
                       bbox: list[float] | None, dpi: int = 150) -> bytes:
    """bbox=None renders the page with no highlight instead of failing."""
```

---

## Phase 8 — Verification agent

```python
# core/agents/tools.py                                         [A]  ⬜
def search_invoices(session, client_id: int, start: date, end: date) -> list[TransactionRow]: ...
def read_contract_clause(session, clause_ref_id: int) -> str: ...
def search_bank_transactions(session, run_id: int, amount_min: float,
                             amount_max: float, start: date, end: date) -> list[TransactionRow]: ...
def check_split_payments(session, client_id: int, target: float,
                         start: date, end: date, tol: float = 0.02) -> list[list[TransactionRow]]: ...

# core/agents/verification_agent.py                            [B]  ⬜
def verify_anomaly(anomaly: Anomaly) -> VerificationResult:
    """LangGraph ReAct loop, max 5 iterations.
       VerificationResult: verdict, explanation, tool_calls, confidence."""
```

---

## Phase 9 — Decision engine

```python
# core/engine/cashflow.py                                      [A]  ⬜
def compute_baseline(session, run_id: int, months: int = 6) -> CashFlowBaseline: ...
def apply_scenario(baseline: CashFlowBaseline, monthly_cost: float,
                   recovered_monthly: float) -> ScenarioResult: ...

# core/ai/decision_analyzer.py                                 [B]  ⬜
def parse_question(q: str) -> ParsedQuestion:
    """-> {what: str, monthly_cost: float, start_month: str|None}"""
def explain_verdict(result: ScenarioResult, parsed: ParsedQuestion) -> str: ...
```

---

## Phase 10–11 — Fine-tuning & evaluation

```python
# training/build_pairs.py                                      [A]  ⬜
def build_pairs(contract_dir: str, out: str) -> tuple[int,int,int]:
    """Returns (train, val, test) counts. Writes .jsonl."""

# training/evaluate.py                                         [A]  ⬜
def evaluate(model_name: str, eval_set: str) -> EvalReport:
    """Same harness for base and tuned. One arg apart — and since ADR-012 that
       arg is the served MODEL NAME, not a vendor: identical weights, adapter
       on or off, so any delta is attributable to our training data."""

# training/serve_model.py — see Phase 5 above. It has been serving base
# weights since then; Phase 10 only teaches it to load an adapter.
```

---

## Status key

⬜ planned · 🔨 in progress · ✅ implemented · ⚠️ implemented but signature changed (say so in `progress.md`)
