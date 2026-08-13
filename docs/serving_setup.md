# Serving the model — Colab and Kaggle, interchangeably

FinSight runs its own open-source model (ADR-011). There is no vendor API key
anywhere. The model lives in a **free notebook GPU session** that you start by
hand, and the app reaches it over a public URL.

Two hosts are supported and they are **fully interchangeable**:

| | Colab | Kaggle |
|---|---|---|
| Role | primary | backup |
| GPU | T4, ~3–4h at a time | T4 x2, 30h/week quota |
| Env var the URL goes in | `COLAB_TUNNEL_URL` | `KAGGLE_TUNNEL_URL` |
| `LLM_PROVIDER` value | `colab_tunnel` | `kaggle_tunnel` |

Both can be running **at the same time**, with both URLs in `.env` at once.
Switching is one dropdown in the app — no restart, no code change.

---

## One-time setup (about 10 minutes, you only do this once)

### 1. Accounts

- **Google account** → <https://colab.research.google.com> — sign in, that's it.
- **Kaggle account** → <https://kaggle.com> — sign up, then **verify your phone
  number** (Settings → Phone Verification). Without it Kaggle gives you no GPU
  and no internet access in notebooks, and both are required here.

You do **not** need a HuggingFace token. `Qwen/Qwen2.5-3B-Instruct` is public.

### 2. Your shared secret

The tunnel URL is public — anyone who finds it could use your GPU quota. So the
server checks a bearer token on every request.

Your key is already generated and sitting in your local `.env`:

```
LLM_API_KEY=finsight-GaK-on1sZuD1sH6Vs92cC6qTEStXPc9p
```

You need the **same value** stored on both hosts, under exactly the name
`LLM_API_KEY`:

- **Colab** — open a notebook, click the 🔑 **key icon** in the left sidebar
  ("Secrets") → **Add new secret** → Name `LLM_API_KEY`, Value the string above
  → toggle **Notebook access** on.
- **Kaggle** — open a notebook, right sidebar **Add-ons → Secrets → Add secret**
  → Label `LLM_API_KEY`, Value the same string → tick **Attached** for this
  notebook.

### 3. Push this repo

The notebook clones the repo to get `training/serve_model.py`. Make sure your
latest commit is on GitHub before you run the cell.

---

## Every session (about 5 minutes, mostly waiting)

### Colab

1. <https://colab.research.google.com> → **New notebook**.
2. **Runtime → Change runtime type → T4 GPU → Save.**
3. Check the 🔑 Secrets panel still has `LLM_API_KEY` toggled on for this notebook.
4. Paste this into a cell and run it:

```python
!git clone -q https://github.com/maybethemuhammadibrahim/Fin.git 2>/dev/null || git -C Fin pull -q
!python Fin/training/serve_model.py --self-test
```

### Kaggle

1. <https://kaggle.com/code> → **New Notebook**.
2. Right sidebar: **Accelerator → GPU T4 x2**, and **Internet → On**.
3. **Add-ons → Secrets** — check `LLM_API_KEY` is attached.
4. Paste the **same cell** and run it.

That is the whole difference between the two hosts: nothing. The script detects
where it is running and adapts.

### What you'll see

```
[serve_model 09:14:02] platform=colab gpu=Tesla T4 model=Qwen/Qwen2.5-3B-Instruct
[serve_model 09:14:03] pip install vllm (this is the slow part)
[serve_model 09:18:40] starting vLLM (half) on port 8000
[serve_model 09:18:41] waiting for the model to finish loading (up to 900s)
[serve_model 09:21:05] model is up
[serve_model 09:21:06] downloading cloudflared
[serve_model 09:21:14] self-test: one chat completion through the public URL
[serve_model 09:21:18] self-test reply: 'READY'
[serve_model 09:21:19] self-test: a wrong key is correctly rejected
====================================================================
  FinSight model endpoint is LIVE on colab
====================================================================

  Paste these two lines into FinSight (.env, Streamlit Secrets, or
  the Endpoints panel in the app):

    COLAB_TUNNEL_URL=https://some-random-words.trycloudflare.com
    LLM_PROVIDER=colab_tunnel
```

**Leave the cell running.** It is the service. Closing the tab kills the URL.

### 5. Point the app at it

Open FinSight → the **Endpoints** panel → pick the host → paste the URL →
**Test**. Green means the app can reach the model. That's it.

Or edit `.env` directly, if you prefer, and restart Streamlit.

---

## Swapping hosts

Because both URLs live in `.env` at the same time, swapping is picking the other
radio button in the Endpoints panel. Nothing else changes — same model name,
same cache (the disk cache is keyed on prompt + model, deliberately **not** on
which host answered), same code path.

Cases where you'll actually do it:

- Colab kicked you off / hit a usage limit → switch to Kaggle mid-demo.
- You want the Kaggle T4 x2 for a long extraction run and Colab for interactive work.
- Colab's session is cold-starting → the warm Kaggle one answers now.

**Failover** is on by default (`LLM_FAILOVER=true`). If the active endpoint is
unreachable and the other one is configured, one request goes there instead, and
the app says so rather than pretending nothing happened.

---

## When it goes wrong

| Symptom | Cause | Fix |
|---|---|---|
| `No GPU visible` | runtime type is CPU | Colab: Runtime → Change runtime type → T4. Kaggle: Accelerator → GPU T4 x2 |
| `No LLM_API_KEY` | secret missing or not attached to this notebook | re-check step 2; the name must match exactly |
| Kaggle: pip install hangs or fails | Internet is off | right sidebar → Internet → On |
| `vLLM needs 7.0+` | Kaggle gave you a P100 | pick T4 x2, or run with `--backend transformers` |
| pip install of vLLM fails | version churn on the host | `!python Fin/training/serve_model.py --self-test --backend transformers` — slower, no grammar constraint, otherwise identical |
| The URL worked, now everything 502s | session died or timed out | re-run the cell, paste the **new** URL (it changes every time) |
| App says "model endpoint is down" but the notebook looks fine | you pasted an old URL | re-copy from the most recent banner |

## Cost and limits

Everything here is free tier. Colab gives you a few hours of T4 at a time and
disconnects on idle; Kaggle gives 30 GPU-hours a week in blocks of up to 12h.
That is the reason the Kaggle copy exists, and the reason the disk cache is
described as demo insurance rather than an optimisation: anything already cached
keeps working after the session dies.
