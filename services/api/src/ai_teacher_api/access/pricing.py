"""What a model call costs, in micro-dollars (1 USD = 1_000_000). List prices from ai.google.dev/gemini-api/docs/pricing (checked 2026-10-17) plus a safety margin,
because our number is an estimate, not Google's invoice. Unknown models are charged like a Pro model, so a new model can never be free by accident."""

MARGIN = 1.15
M = 1_000_000  # per 1M tokens: (input, output) USD
TEXT = {
    "gemini-3.6-flash": (0.75, 3.75), "gemini-3.8-flash": (0.75, 3.75), "gemini-3.5-flash": (0.75, 3.75), "gemini-3-flash-preview": (0.75, 3.75),
    "gemini-2.5-flash": (0.75, 3.75), "gemini-3.1-pro-preview": (2.0, 12.0), "gemini-2.5-pro": (2.0, 12.0),
}
UNKNOWN = (2.0, 12.0)
IMAGE_USD = {"gemini-3.1-flash-image": 0.067, "gemini-2.5-flash-image": 0.039}
IMAGE_UNKNOWN = 0.10
SEARCH_USD = 0.014  # per grounded request
TTS_USD_PER_MCHAR = 30.0  # Chirp 3 HD
LIVE_USD_PER_MIN = {"in_audio": 0.005, "out_audio": 0.018, "context": 0.004}  # context: the text tokens re-read every turn, rough


def micro(usd: float) -> int:
    return round(usd * M * MARGIN)


def _tok(x) -> int:
    return int(x or 0)


def text_cost(model: str, prompt: int, output: int, searches: int = 0) -> int:
    pin, pout = TEXT.get(model, UNKNOWN)
    return micro((prompt * pin + output * pout) / M + searches * SEARCH_USD)


def image_cost(model: str, n_images: int, prompt: int = 0) -> int:
    pin = TEXT.get(model, (0.75, 0))[0]
    return micro(n_images * IMAGE_USD.get(model, IMAGE_UNKNOWN) + prompt * pin / M)


def response_cost(model: str, resp) -> int:
    """Cost of one generate_content response (or the last chunk of a stream)."""
    um = getattr(resp, "usage_metadata", None)
    prompt = _tok(getattr(um, "prompt_token_count", 0)) + _tok(getattr(um, "tool_use_prompt_token_count", 0))
    out = _tok(getattr(um, "candidates_token_count", 0)) + _tok(getattr(um, "thoughts_token_count", 0))
    if "image" in model:
        n = 0
        for c in getattr(resp, "candidates", None) or []:
            for p in getattr(getattr(c, "content", None), "parts", None) or []:
                if getattr(p, "inline_data", None) and str(getattr(p.inline_data, "mime_type", "")).startswith("image/"):
                    n += 1
        return image_cost(model, n, prompt)
    searches = 0
    for c in getattr(resp, "candidates", None) or []:
        gm = getattr(c, "grounding_metadata", None)
        searches = max(searches, len(getattr(gm, "web_search_queries", None) or []))
    return text_cost(model, prompt, out, searches)


def tts_cost(chars: int) -> int:
    return micro(chars * TTS_USD_PER_MCHAR / M)


def live_cost(out_audio_s: float, in_audio_s: float, wall_s: float) -> int:
    p = LIVE_USD_PER_MIN
    return micro((out_audio_s * p["out_audio"] + in_audio_s * p["in_audio"] + wall_s * p["context"]) / 60)
