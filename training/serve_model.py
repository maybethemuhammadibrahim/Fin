"""[B] Runs IN Colab/Kaggle: OpenAI-compatible endpoint over a tunnel. Phase 5.

Live from Phase 5 with BASE Qwen 2.5 3B Instruct (ADR-012); Phase 10 adds the
QLoRA adapter under a second model name (`--lora NAME=PATH`, no rewrite). Must
reject requests without LLM_API_KEY — a Cloudflare quick tunnel is a public URL.

ONE FILE, BOTH HOSTS. The whole point of this module is that Colab and Kaggle
are interchangeable: the same bootstrap cell runs here, the platform is detected
rather than configured, and the banner at the end names the right env var for
whichever host you happen to be on.

    !git clone -q https://github.com/maybethemuhammadibrahim/Fin.git
    !python Fin/training/serve_model.py --self-test

Backends:
  vllm         (default) vLLM's own OpenAI server — it IS a FastAPI app, it
               enforces --api-key itself, and because we control the server it
               can constrain generation to a JSON schema (the upgrade ADR-011
               bought us; see ADR-015).
  transformers a small FastAPI app implementing the same two routes by hand.
               Needed where vLLM will not run — notably Kaggle's P100, which is
               compute capability 6.0 and below vLLM's 7.0 floor.

Nothing in this file is imported by the app. It runs on the GPU host only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_MODEL = "Qwen/Qwen2.5-3B-Instruct"
DEFAULT_PORT = 8000
SECRET_NAME = "LLM_API_KEY"

#: cloudflared quick tunnels need no account and no login. The URL is random and
#: rotates on every start — which is exactly why settings.api_base is read at
#: call time and why the app has a paste-a-new-URL switcher.
CLOUDFLARED_URL = (
    "https://github.com/cloudflare/cloudflared/releases/latest/download/"
    "cloudflared-linux-amd64"
)
TUNNEL_RE = re.compile(r"https://[-a-z0-9]+\.trycloudflare\.com")

#: Which env var the host's URL belongs in, on the app side.
ENV_VAR_FOR_PLATFORM = {
    "colab": "COLAB_TUNNEL_URL",
    "kaggle": "KAGGLE_TUNNEL_URL",
    "other": "CUSTOM_BASE_URL",
}
PROVIDER_FOR_PLATFORM = {
    "colab": "colab_tunnel",
    "kaggle": "kaggle_tunnel",
    "other": "custom",
}


def log(message: str) -> None:
    """Timestamped, flushed. Notebook output buffers otherwise."""
    print(f"[serve_model {time.strftime('%H:%M:%S')}] {message}", flush=True)


# ---------------------------------------------------------------------------
# Platform
# ---------------------------------------------------------------------------


def detect_platform() -> str:
    """"colab" | "kaggle" | "other". Never raises."""
    if "google.colab" in sys.modules:
        return "colab"
    try:
        import google.colab  # noqa: F401

        return "colab"
    except ImportError:
        pass
    if os.environ.get("KAGGLE_KERNEL_RUN_TYPE") or Path("/kaggle").is_dir():
        return "kaggle"
    return "other"


def read_secret(name: str, platform: str) -> str | None:
    """The shared bearer secret, from wherever this host keeps secrets.

    Colab  -> Secrets panel (key icon), toggled on for this notebook
    Kaggle -> Add-ons > Secrets, attached to this notebook
    other  -> a plain environment variable

    An environment variable always wins, so `LLM_API_KEY=... python serve_model.py`
    works everywhere for a quick test.
    """
    from_env = os.environ.get(name)
    if from_env:
        return from_env.strip()

    if platform == "colab":
        try:
            from google.colab import userdata

            return (userdata.get(name) or "").strip() or None
        except Exception as exc:  # secret missing, or access not granted
            log(f"Colab secret {name!r} unavailable: {exc}")
            return None

    if platform == "kaggle":
        try:
            from kaggle_secrets import UserSecretsClient

            return (UserSecretsClient().get_secret(name) or "").strip() or None
        except Exception as exc:
            log(f"Kaggle secret {name!r} unavailable: {exc}")
            return None

    return None


def gpu_report() -> tuple[str | None, tuple[int, int] | None]:
    """(device name, compute capability). (None, None) when there is no GPU."""
    try:
        import torch
    except ImportError:
        return None, None
    if not torch.cuda.is_available():
        return None, None
    return torch.cuda.get_device_name(0), torch.cuda.get_device_capability(0)


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


def pip_install(*packages: str) -> bool:
    log(f"pip install {' '.join(packages)} (this is the slow part)")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-q", *packages],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        log(f"pip failed:\n{result.stdout[-2000:]}\n{result.stderr[-2000:]}")
        return False
    return True


def have(module: str) -> bool:
    import importlib.util

    return importlib.util.find_spec(module) is not None


def ensure_cloudflared() -> str | None:
    """Path to a runnable cloudflared, downloading it if the host lacks one."""
    existing = shutil.which("cloudflared")
    if existing:
        return existing

    target = Path("/tmp/cloudflared")
    if not target.exists():
        log("downloading cloudflared")
        try:
            urllib.request.urlretrieve(CLOUDFLARED_URL, target)
        except Exception as exc:
            log(f"could not download cloudflared: {exc}")
            return None
    target.chmod(0o755)
    return str(target)


# ---------------------------------------------------------------------------
# Backend: vLLM
# ---------------------------------------------------------------------------


def start_vllm(model: str, port: int, api_key: str, args) -> subprocess.Popen | None:
    """Launch vLLM's OpenAI server as a child process. None if it cannot start."""
    if not have("vllm") and not pip_install("vllm"):
        return None

    name, capability = gpu_report()
    if capability and capability[0] < 7:
        log(
            f"{name} is compute capability {capability[0]}.{capability[1]}; vLLM "
            "needs 7.0+. Use --backend transformers, or pick a T4 accelerator."
        )
        return None

    # T4 (7.5) has no bfloat16. Ampere and later do, and prefer it.
    dtype = "bfloat16" if capability and capability[0] >= 8 else "half"

    command = [
        sys.executable,
        "-m",
        "vllm.entrypoints.openai.api_server",
        "--model", model,
        "--served-model-name", model,
        "--port", str(port),
        "--host", "127.0.0.1",
        "--api-key", api_key,
        "--dtype", dtype,
        "--max-model-len", str(args.max_model_len),
        "--gpu-memory-utilization", str(args.gpu_memory_utilization),
    ]
    # Phase 10 lands here: the adapter is served alongside the base weights
    # under its own name, so base-vs-tuned is one LLM_MODEL value apart.
    if args.lora:
        command += ["--enable-lora", "--lora-modules", *args.lora]

    log(f"starting vLLM ({dtype}) on port {port}")
    return subprocess.Popen(command, stdout=sys.stdout, stderr=sys.stderr)


# ---------------------------------------------------------------------------
# Backend: transformers + FastAPI (the fallback vLLM's GPU floor makes necessary)
# ---------------------------------------------------------------------------


def run_transformers_server(model: str, port: int, api_key: str, args) -> None:
    """Blocking. Implements the two routes llm_client actually calls."""
    missing = [p for p in ("fastapi", "uvicorn", "transformers", "torch") if not have(p)]
    if missing and not pip_install(*[p for p in missing if p != "torch"]):
        raise SystemExit("cannot install the transformers backend's dependencies")

    import torch
    import uvicorn
    from fastapi import FastAPI, Header, HTTPException
    from transformers import AutoModelForCausalLM, AutoTokenizer

    log(f"loading {model} with transformers (no vLLM)")
    tokenizer = AutoTokenizer.from_pretrained(model)
    weights = AutoModelForCausalLM.from_pretrained(
        model,
        torch_dtype=torch.float16,
        device_map="auto",
    )
    weights.eval()

    app = FastAPI(title="FinSight model endpoint")

    def authorise(header: str | None) -> None:
        if header != f"Bearer {api_key}":
            raise HTTPException(status_code=401, detail="bad or missing bearer token")

    @app.get("/v1/models")
    def models(authorization: str | None = Header(default=None)):
        authorise(authorization)
        return {"object": "list", "data": [{"id": model, "object": "model"}]}

    @app.post("/v1/chat/completions")
    def chat(body: dict, authorization: str | None = Header(default=None)):
        authorise(authorization)
        messages = body.get("messages") or []
        max_tokens = int(body.get("max_tokens") or 1024)
        temperature = float(body.get("temperature") if body.get("temperature") is not None else 0.0)

        # No grammar constraint on this path — the client's repair-retry (ADR-004)
        # is what covers it. Nudging the model with an opening brace is the one
        # cheap thing we can do here.
        prefix = ""
        wants_json = (body.get("response_format") or {}).get("type", "").startswith("json")

        prompt = tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        if wants_json:
            prefix = "{"
            prompt += prefix

        inputs = tokenizer(prompt, return_tensors="pt").to(weights.device)
        with torch.no_grad():
            generated = weights.generate(
                **inputs,
                max_new_tokens=max_tokens,
                do_sample=temperature > 0,
                temperature=temperature or None,
                pad_token_id=tokenizer.eos_token_id,
            )
        completion = prefix + tokenizer.decode(
            generated[0][inputs["input_ids"].shape[-1]:], skip_special_tokens=True
        )
        return {
            "id": f"chatcmpl-{int(time.time() * 1000)}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": completion},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": int(inputs["input_ids"].shape[-1]),
                "completion_tokens": int(generated.shape[-1] - inputs["input_ids"].shape[-1]),
                "total_tokens": int(generated.shape[-1]),
            },
        }

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


# ---------------------------------------------------------------------------
# Tunnel
# ---------------------------------------------------------------------------


def start_tunnel(binary: str, port: int, timeout: int = 90) -> tuple[subprocess.Popen, str] | None:
    """Open a quick tunnel and return (process, public URL)."""
    process = subprocess.Popen(
        [binary, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{port}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    deadline = time.time() + timeout
    while time.time() < deadline:
        line = process.stdout.readline() if process.stdout else ""
        if not line:
            if process.poll() is not None:
                log("cloudflared exited before printing a URL")
                return None
            continue
        match = TUNNEL_RE.search(line)
        if match:
            return process, match.group(0)
    log("cloudflared printed no URL within the timeout")
    process.terminate()
    return None


# ---------------------------------------------------------------------------
# Health and self-test
# ---------------------------------------------------------------------------


def _request(url: str, api_key: str, payload: dict | None = None, timeout: int = 30) -> dict | None:
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST" if data else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode())
    except Exception:
        return None


def wait_until_ready(port: int, api_key: str, timeout: int) -> bool:
    """Poll /v1/models until the weights are loaded. Cold start is minutes."""
    log(f"waiting for the model to finish loading (up to {timeout}s)")
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _request(f"http://127.0.0.1:{port}/v1/models", api_key, timeout=5):
            log("model is up")
            return True
        time.sleep(5)
    return False


def self_test(base_url: str, api_key: str, model: str) -> bool:
    """One real round trip THROUGH the tunnel, so the URL is proven before it
    gets pasted anywhere. A working localhost and a working tunnel are not the
    same claim."""
    log("self-test: one chat completion through the public URL")
    body = _request(
        f"{base_url}/v1/chat/completions",
        api_key,
        {
            "model": model,
            "messages": [
                {"role": "system", "content": "Reply with one word."},
                {"role": "user", "content": "Say READY."},
            ],
            "max_tokens": 8,
            "temperature": 0.0,
        },
        timeout=120,
    )
    if not body:
        log("SELF-TEST FAILED — the tunnel did not answer")
        return False
    reply = body.get("choices", [{}])[0].get("message", {}).get("content", "")
    log(f"self-test reply: {reply.strip()!r}")

    unauthorised = _request(f"{base_url}/v1/models", "wrong-key", timeout=15)
    if unauthorised is not None:
        log("WARNING: the endpoint answered a request with the WRONG key. It is open to anyone.")
        return False
    log("self-test: a wrong key is correctly rejected")
    return True


def banner(platform: str, base_url: str, model: str) -> None:
    variable = ENV_VAR_FOR_PLATFORM[platform]
    provider = PROVIDER_FOR_PLATFORM[platform]
    print(
        "\n"
        + "=" * 68
        + f"\n  FinSight model endpoint is LIVE on {platform}\n"
        + "=" * 68
        + "\n\n  Paste these two lines into FinSight (.env, Streamlit Secrets, or\n"
        "  the Endpoints panel in the app):\n\n"
        f"    {variable}={base_url}\n"
        f"    LLM_PROVIDER={provider}\n\n"
        f"  Model: {model}\n"
        "  Keep this cell running. Closing the notebook kills the URL, and a\n"
        "  restart produces a different one.\n"
        + "=" * 68
        + "\n",
        flush=True,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve FinSight's model from Colab or Kaggle.")
    parser.add_argument("--model", default=os.environ.get("LLM_MODEL", DEFAULT_MODEL))
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--backend",
        choices=("auto", "vllm", "transformers"),
        default="auto",
        help="auto tries vLLM and falls back to transformers if it cannot start",
    )
    parser.add_argument("--max-model-len", type=int, default=8192)
    parser.add_argument("--gpu-memory-utilization", type=float, default=0.90)
    parser.add_argument(
        "--lora",
        action="append",
        metavar="NAME=PATH",
        help="serve a QLoRA adapter alongside the base weights (Phase 10)",
    )
    parser.add_argument("--startup-timeout", type=int, default=900)
    parser.add_argument("--self-test", action="store_true", help="prove the tunnel before printing it")
    parser.add_argument("--no-tunnel", action="store_true", help="local only; skip cloudflared")
    args = parser.parse_args()

    platform = detect_platform()
    device, capability = gpu_report()
    log(f"platform={platform} gpu={device or 'NONE'} model={args.model}")

    if device is None:
        log(
            "No GPU visible. Colab: Runtime > Change runtime type > T4 GPU. "
            "Kaggle: Settings > Accelerator > GPU T4 x2, and Internet ON."
        )
        return 1

    api_key = read_secret(SECRET_NAME, platform)
    if not api_key:
        log(
            f"No {SECRET_NAME}. The tunnel is a PUBLIC URL, so this server will not "
            "start without one. Add it in Colab's Secrets panel (key icon) or "
            "Kaggle's Add-ons > Secrets, using exactly that name."
        )
        return 1

    server: subprocess.Popen | None = None
    backend = args.backend

    if backend in ("auto", "vllm"):
        server = start_vllm(args.model, args.port, api_key, args)
        if server is None:
            if backend == "vllm":
                return 1
            log("falling back to the transformers backend")
            backend = "transformers"
        else:
            backend = "vllm"

    if backend == "transformers":
        # Blocking, in-process: no child to supervise, so the tunnel goes up
        # first and the banner is printed from a background thread.
        import threading

        tunnel_holder: dict[str, object] = {}

        def open_tunnel_when_ready() -> None:
            if not wait_until_ready(args.port, api_key, args.startup_timeout):
                log("the transformers server never became ready")
                return
            if args.no_tunnel:
                banner(platform, f"http://127.0.0.1:{args.port}", args.model)
                return
            binary = ensure_cloudflared()
            if not binary:
                return
            opened = start_tunnel(binary, args.port)
            if not opened:
                return
            tunnel_holder["process"], url = opened
            if args.self_test and not self_test(url, api_key, args.model):
                log("self-test failed; the URL below may not work")
            banner(platform, url, args.model)

        threading.Thread(target=open_tunnel_when_ready, daemon=True).start()
        run_transformers_server(args.model, args.port, api_key, args)
        return 0

    # vLLM path: supervise the child, then tunnel.
    try:
        if not wait_until_ready(args.port, api_key, args.startup_timeout):
            log("the model never became ready — scroll up for vLLM's own error")
            server.terminate()
            return 1

        base_url = f"http://127.0.0.1:{args.port}"
        tunnel = None
        if not args.no_tunnel:
            binary = ensure_cloudflared()
            if not binary:
                return 1
            opened = start_tunnel(binary, args.port)
            if not opened:
                server.terminate()
                return 1
            tunnel, base_url = opened

        if args.self_test and not self_test(base_url, api_key, args.model):
            log("self-test failed — do not paste this URL yet")

        banner(platform, base_url, args.model)

        # Block. The notebook cell staying alive IS the service.
        while server.poll() is None:
            time.sleep(30)
        log("the model server exited")
        if tunnel:
            tunnel.terminate()
        return server.returncode or 0
    except KeyboardInterrupt:
        log("stopping")
        server.send_signal(signal.SIGINT)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
