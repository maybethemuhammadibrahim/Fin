"""[B] Runs IN Colab/Kaggle: OpenAI-compatible endpoint over a tunnel. Phase 5.

Live from Phase 5 with BASE Qwen 2.5 3B Instruct (ADR-012); Phase 10 adds the
QLoRA adapter under a second model name. Must reject requests without
LLM_API_KEY — a Cloudflare quick tunnel is a public URL.
"""
