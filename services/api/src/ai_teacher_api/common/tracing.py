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
    try:  # the plain google-genai calls too (live class planner, figures, picture checks, safety gate)
        from openinference.instrumentation.google_genai import GoogleGenAIInstrumentor

        GoogleGenAIInstrumentor().instrument()
    except Exception as e:  # noqa: BLE001
        print(f"[tracing] genai instrumentation off: {e!r}", flush=True)
    _client = get_client()
    _tag_users()
    ok = _client.auth_check()
    print(f"[tracing] Langfuse connected: {ok}", flush=True)
    return _client if ok else None


def flush() -> None:
    if _client is not None:
        _client.flush()


def _tag_users() -> None:
    """Every span carries the signed-in user (a short hash of the email, not the address) so cost and conversations can be found per user in Langfuse."""
    import hashlib

    from opentelemetry import trace
    from opentelemetry.sdk.trace import SpanProcessor

    from ai_teacher_api.access import usage

    class UserTagger(SpanProcessor):
        def on_start(self, span, parent_context=None):
            u = usage.current()
            if u and u.get("email"):
                uid = "u-" + hashlib.sha1(u["email"].encode()).hexdigest()[:10]
                span.set_attribute("user.id", uid)
                span.set_attribute("langfuse.user.id", uid)

    provider = trace.get_tracer_provider()
    if hasattr(provider, "add_span_processor"):
        provider.add_span_processor(UserTagger())
