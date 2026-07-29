"""[B] Client for our self-hosted OpenAI-compatible endpoint (ADR-011). Phase 5.

Endpoint chosen by LLM_PROVIDER; no frontier model API is ever called. Needs a
generous timeout and one cold-start retry, and must fail visibly when the
notebook session is down.
"""
