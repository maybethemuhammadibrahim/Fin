# INTERFACES — The Contract Between User A and User B

> **This file is written BEFORE the code, not after.**
> When a phase needs a function that crosses the A/B boundary, the signature goes here first. The other person then writes against it immediately using a stub, without waiting for the real implementation.
>
> **Changing a signature that already appears here requires telling the other person.** Silently changing it is the single fastest way to break each other's work.

**Status:** Phase 0 complete. Phase 0's own signatures are ✅; everything from Phase 1 down is still the *planned* contract. Mark each `✅` as it lands.

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
# core/db/database.py                                          [A]  ⬜
def get_session() -> Session: ...
def init_db() -> None: ...

# core/db/queries.py                                           [B]  ⬜
def get_summary_stats(session, run_id: int) -> SummaryStats: ...
def list_anomalies(session, run_id: int, status: str | None = None) -> list[Anomaly]: ...
def get_clause_reference(session, clause_ref_id: int) -> ClauseRefRow | None: ...
def list_clients(session, run_id: int) -> list[ClientRow]: ...
def get_document(session, document_id: int) -> DocumentRow | None: ...
def create_run(session, label: str) -> int: ...
```

---

## Phase 2 — Seeding & UI

```python
# scripts/seed_demo.py                                         [A]  ⬜
def seed_run(session, scenario_dir: str, label: str) -> int:
    """Loads a built scenario into the DB. Returns run_id.
       Writes every table the UI reads, so B's pages work end-to-end."""

# app/components/*.py                                          [B]  ⬜
def render_summary_cards(stats: SummaryStats) -> None: ...
def render_anomaly_table(anomalies: list[Anomaly]) -> int | None:
    """Returns the anomaly_id of the clicked row, or None."""
def render_clause_viewer(clause_ref_id: int) -> None: ...
def render_cash_flow_chart(baseline: list[float], recovered: list[float]) -> None: ...
```

---

## Phase 3 — Data sourcing

```python
# data_sourcing/fetch_contracts.py                             [A]  ⬜
def fetch_cuad(limit: int = 200, out_dir: str = "data/corpus/contracts") -> list[Path]: ...
def filter_service_contracts(paths: list[Path]) -> list[Path]:
    """Keyword filter for retainer/escalation/discount language.
       Expect ~15-25% retention on CUAD."""
def fetch_edgar_msa(count: int, out_dir: str) -> list[Path]: ...

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
