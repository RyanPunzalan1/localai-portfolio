"""PoC workaround, not a fix: replace Inspect's tiktoken token estimate (which downloads o200k_base from an
OpenAI-hosted blob on first use) with a local length-based estimate, so runs stay offline."""
import inspect_ai.model._tokens as _t
import inspect_ai.model._model as _m
def _estimate(text, *a, **k):
    return max(1, int(len(str(text)) / 4 * 1.1))
_t.count_text_tokens = _estimate
if hasattr(_m, "count_text_tokens"):
    _m.count_text_tokens = _estimate
