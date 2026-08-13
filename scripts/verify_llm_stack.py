"""[B] Prove the LLM client works, with no GPU and no notebook session.

    python scripts/verify_llm_stack.py

Stands up a stub OpenAI-compatible server on localhost and drives
`llm_client` / `endpoints` / `cache` against it. Everything that is hard to
check when a real endpoint is involved gets checked here: failover between
Colab and Kaggle, the cache surviving a host swap, JSON-mode negotiation
downwards, the repair retry, and the promise that nothing ever raises.

It touches **nothing real** — the cache directory and the endpoint override file
are both redirected into a temporary directory for the duration, so running this
cannot delete a pre-warmed demo cache or change which host is live.

Phase 1's 47 assertions ran from a throwaway script and could not be re-run
(known issue #15). This one lives in the repo for that reason. `tests/` stays
docstring-only until Phase 6 owns it.
"""

from __future__ import annotations

import json
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

KEY = "verify-key"
MODEL = "verify-model"

VALID_RULES = {
    "client_name": "Starter Labs",
    "contract_start_date": "2025-01-15",
    "contract_end_date": "2026-01-14",
    "base_amount": 6000.0,
    "currency": "USD",
    "billing_frequency": "monthly",
    "payment_terms": "Net 30",
    "escalation": {
        "percentage": 8.0,
        "after_months": 12,
        "clause_text": "Fees shall increase by 8% on each anniversary of the Effective Date.",
    },
    "discounts": [],
    "milestones": [],
}


# ---------------------------------------------------------------------------
# The stub endpoint
# ---------------------------------------------------------------------------


class _Handler(BaseHTTPRequestHandler):
    mode = "good"
    calls: list[dict] = []

    def log_message(self, *args):
        pass

    def _send(self, code: int, body: dict) -> None:
        payload = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _authed(self) -> bool:
        return self.headers.get("Authorization") == f"Bearer {KEY}"

    def do_GET(self):
        if not self._authed():
            return self._send(401, {"error": "bad key"})
        if self.path == "/v1/models":
            return self._send(200, {"object": "list", "data": [{"id": MODEL}]})
        self._send(404, {"error": "no such route"})

    def do_POST(self):
        if not self._authed():
            return self._send(401, {"error": "bad key"})
        length = int(self.headers.get("Content-Length", 0))
        request = json.loads(self.rfile.read(length) or b"{}")
        self.calls.append(request)

        if self.mode == "dead":
            return self._send(503, {"error": "session gone"})
        if self.mode == "no_schema" and (request.get("response_format") or {}).get("type") == "json_schema":
            return self._send(400, {"error": "guided decoding unsupported"})

        content = json.dumps(VALID_RULES)
        if self.mode == "broken_once" and len(self.calls) == 1:
            content = 'Sure!\n```json\n{"client_name": }\n```'
        self._send(
            200,
            {
                "id": "chatcmpl-verify",
                "object": "chat.completion",
                "model": request.get("model"),
                "choices": [
                    {"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}
                ],
            },
        )


def start_stub(mode: str) -> tuple[HTTPServer, str, type]:
    """A subclass per server: two endpoints must be independently alive or dead."""
    handler = type(f"Handler_{mode}_{id(mode)}", (_Handler,), {"mode": mode, "calls": []})
    server = HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_port}", handler


# ---------------------------------------------------------------------------
# Assertions
# ---------------------------------------------------------------------------

passed = 0
failed = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label}  {detail}")


def main() -> int:
    import os

    os.environ.setdefault("LLM_API_KEY", KEY)
    os.environ["LLM_API_KEY"] = KEY
    os.environ["LLM_MODEL"] = MODEL
    os.environ["LLM_FAILOVER"] = "true"
    os.environ["LLM_CACHE_ENABLED"] = "true"

    from core.ai import cache, endpoints, llm_client
    from core.ai.schemas import ContractRules

    with tempfile.TemporaryDirectory() as sandbox:
        # Redirect every piece of on-disk state into the sandbox.
        cache.CACHE_DIR = Path(sandbox) / "cache"
        endpoints.OVERRIDE_PATH = Path(sandbox) / "endpoint_override.json"

        print("\n1. nothing configured")
        result = llm_client.complete_json("hello", ContractRules)
        check("complete_json returns None instead of raising", result is None)
        check("last_error explains why", "not set" in (llm_client.last_error() or ""))
        check("health() is False", llm_client.health() is False)

        print("\n2. colab answers")
        colab, colab_url, colab_handler = start_stub("good")
        endpoints.set_url("colab_tunnel", colab_url)
        endpoints.set_active("colab_tunnel")
        check("probe reports live", endpoints.probe().ok, endpoints.probe().detail)
        rules = llm_client.complete_json("extract", ContractRules, system="sys")
        check("valid ContractRules parsed", isinstance(rules, ContractRules))
        check("a JSON schema was sent",
              (colab_handler.calls[0].get("response_format") or {}).get("type") == "json_schema")
        check("the host that answered is recorded",
              (endpoints.last_answered() or {}).get("provider") == "colab_tunnel")

        print("\n3. cache")
        before = len(colab_handler.calls)
        again = llm_client.complete_json("extract", ContractRules, system="sys")
        check("an identical call makes no request", len(colab_handler.calls) == before)
        check("the cached value is equal", again == rules)

        print("\n4. the cache is host-independent")
        kaggle, kaggle_url, _ = start_stub("dead")
        endpoints.set_url("kaggle_tunnel", kaggle_url)
        endpoints.set_active("kaggle_tunnel")
        check("a cached answer survives switching to a DEAD host",
              llm_client.complete_json("extract", ContractRules, system="sys") == rules)

        print("\n5. failover")
        cache.clear()
        outcome = llm_client.call("an uncached prompt", system="sys")
        check("failed over to the live host", outcome.provider == "colab_tunnel", str(outcome.error))
        check("the failover is flagged, not silent", outcome.was_failover is True)
        check("the UI can see it happened", (endpoints.last_answered() or {}).get("failover") is True)

        print("\n6. a server without grammar support")
        cache.clear()
        llm_client._JSON_MODE.clear()
        _, plain_url, _ = start_stub("no_schema")
        endpoints.set_url("custom", plain_url)
        endpoints.set_active("custom")
        check("negotiated down to json_object and still parsed",
              isinstance(llm_client.complete_json("extract", ContractRules), ContractRules))
        check("the negotiated mode is remembered",
              llm_client._JSON_MODE.get(plain_url) == "json_object")

        print("\n7. repair retry")
        cache.clear()
        llm_client._JSON_MODE.clear()
        _, repair_url, repair_handler = start_stub("broken_once")
        endpoints.set_url("custom", repair_url)
        check("recovered from invalid JSON",
              isinstance(llm_client.complete_json("extract", ContractRules), ContractRules))
        check("it took exactly two round trips", len(repair_handler.calls) == 2,
              str(len(repair_handler.calls)))

        print("\n8. JSON pulled out of prose")
        check("code fences", llm_client._strip_to_json('Sure!\n```json\n{"a": 1}\n```') == '{"a": 1}')
        check("nested braces", llm_client._strip_to_json('x {"a": {"b": 2}} y') == '{"a": {"b": 2}}')
        check("a brace inside a string", llm_client._strip_to_json('{"a": "}"}') == '{"a": "}"}')

        print("\n9. wrong bearer token")
        os.environ["LLM_API_KEY"] = "wrong"
        import core.config as config_module

        config_module.get_settings.cache_clear()
        config_module.settings = config_module.get_settings()
        endpoints.settings = config_module.settings
        check("the probe says 401 in plain words", "401" in endpoints.probe().detail)

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
