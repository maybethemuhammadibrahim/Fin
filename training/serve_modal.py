"""[B] Serve the same Qwen 2.5 3B on Modal, as a peer of the two notebooks.

    pip install modal
    modal setup                     # once, opens a browser
    modal deploy training/serve_modal.py

Deploying prints a URL that looks like:

    https://<workspace>--finsight-llm-serve.modal.run

Put that in `.env` as MODAL_BASE_URL (or paste it on the Model endpoint page)
and it is reachable exactly like a tunnel — same OpenAI-compatible routes, same
`LLM_API_KEY` header, same `LLM_MODEL` name. Nothing else in FinSight changes.

**Why this is not a departure from ADR-011.** ADR-011 forbids calling a
third-party *model* API. Modal is rented hardware, not a model vendor: the
weights are the same open-source Qwen 2.5 3B we serve from Colab, downloaded by
this file, running under vLLM exactly as the notebook does. Swapping a free T4
for a rented one changes who owns the GPU, not who owns the model. Phase 10's
adapter loads here the same way it loads in the notebook.

**What it is actually for.** The notebooks are the problem this fixes:

* their URL changes on every restart, so `.env` goes stale constantly
* they idle out, and a dead session takes the whole app down (known issue #6)
* a cold start is ~8 minutes of pip install plus weight download

Modal keeps a stable URL and a warm image, so it is the sensible failover
target and the right thing to point a live demo at. `endpoints.fallback()` tries
it first for that reason.

**Cost.** Billed per second of GPU time, only while a request is in flight.
`scaledown_window` below decides how long a warm container waits before
shutting down — the trade is idle cost against cold-start latency. With
`min_containers=0` an idle deployment costs nothing, but the first request after
a quiet period pays a cold start. See CONTAINER_IDLE_SECONDS.
"""

from __future__ import annotations

import os

import modal

# ---------------------------------------------------------------------------
# Configuration — deliberately the same knobs serve_model.py exposes
# ---------------------------------------------------------------------------

MODEL_NAME = os.environ.get("LLM_MODEL", "Qwen/Qwen2.5-3B-Instruct")

#: L4 is the cheapest card that comfortably holds 3B in fp16 with room for a
#: real KV cache, and unlike a T4 it supports bfloat16, so we do not need the
#: `--dtype half` workaround the notebook needs. "T4" also works and is cheaper
#: still; "A10G" is the step up if Phase 10's adapter wants more headroom.
GPU = os.environ.get("MODAL_GPU", "L4")

#: How long a container stays warm after its last request. Longer means fewer
#: cold starts and more idle cost. Two minutes is tuned for demo use: a run of
#: 35-55 extraction calls stays inside one warm container.
CONTAINER_IDLE_SECONDS = 120

#: A cold start downloads nothing (weights are baked into the image below) but
#: still loads 3B onto the card. Matches LLM_TIMEOUT_SECONDS on the client.
STARTUP_TIMEOUT = 600

APP_NAME = "finsight-llm"

# ---------------------------------------------------------------------------
# Image — weights baked in at build time, so a cold start does not download 6GB
# ---------------------------------------------------------------------------


def _download_weights() -> None:
    from huggingface_hub import snapshot_download

    snapshot_download(MODEL_NAME, ignore_patterns=["*.pt", "*.bin"])


image = (
    modal.Image.debian_slim(python_version="3.12")
    # Pinned on purpose. Unpinned `pip install vllm` is what broke Colab by
    # dragging in a torch newer than the preinstalled torchaudio (issue #50).
    # Here the image is ours alone, but the pin is still what makes a rebuild
    # reproducible rather than "whatever was on PyPI that morning".
    .pip_install("vllm==0.27.1", "huggingface_hub[hf_transfer]==0.35.3")
    .env({"HF_HUB_ENABLE_HF_TRANSFER": "1"})
    .run_function(_download_weights, secrets=[modal.Secret.from_name("finsight-llm")])
)

app = modal.App(APP_NAME)


# ---------------------------------------------------------------------------
# The server
# ---------------------------------------------------------------------------


@app.function(
    image=image,
    gpu=GPU,
    scaledown_window=CONTAINER_IDLE_SECONDS,
    timeout=STARTUP_TIMEOUT,
    # Same shared secret the notebook uses, under the same name. Create it with:
    #   modal secret create finsight-llm LLM_API_KEY=<your key>
    secrets=[modal.Secret.from_name("finsight-llm")],
)
@modal.concurrent(max_inputs=8)
@modal.web_server(port=8000, startup_timeout=STARTUP_TIMEOUT)
def serve() -> None:
    """Run vLLM's own OpenAI server, exactly as the notebook does.

    vLLM's server IS a FastAPI app implementing /v1/chat/completions, so there
    is nothing for us to write. `--api-key` makes it reject requests without the
    bearer token, which matters here for the same reason it matters on a quick
    tunnel: this URL is public.
    """
    import subprocess

    api_key = os.environ["LLM_API_KEY"]

    subprocess.Popen(
        [
            "python",
            "-m",
            "vllm.entrypoints.openai.api_server",
            "--model", MODEL_NAME,
            "--served-model-name", MODEL_NAME,
            "--host", "0.0.0.0",
            "--port", "8000",
            "--api-key", api_key,
            "--max-model-len", "8192",
            # No --dtype: unlike the T4, an L4/A10G does bfloat16 natively and
            # vLLM picks it. Forcing `half` here would be copying a workaround
            # for hardware we are no longer on.
        ]
    )
