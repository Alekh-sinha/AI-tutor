"""Langfuse tracing for every ADK model and tool call. Switches on only when the Langfuse keys are in services/api/.env."""

import os

from ai_teacher_api.common import settings  # noqa: F401  (loads .env)

_client = None


def init():
    """Instrument ADK (OpenTelemetry -> Langfuse). Returns the Langfuse client or None when keys are missing."""
    global _client
    if _client is not None:
        return _client
    if not (os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY")):
        print("[tracing] Langfuse keys not set: tracing is off", flush=True)
        return None
    from langfuse import get_client
    from openinference.instrumentation.google_adk import GoogleADKInstrumentor

    GoogleADKInstrumentor().instrument()
    _client = get_client()
    ok = _client.auth_check()
    print(f"[tracing] Langfuse connected: {ok}", flush=True)
    return _client if ok else None


def flush() -> None:
    if _client is not None:
        _client.flush()
