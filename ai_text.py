"""Helpers for the Fable model: text extraction and safe request defaults.

Fable always thinks, so replies start with a ThinkingBlock and thinking shares the max_tokens
budget. install_fable_defaults() patches Messages.create once so every call site in the project
gets a roomy token budget and a default effort level without editing each call.
"""

FABLE_DEFAULT_EFFORT = "medium"
FABLE_MIN_MAX_TOKENS = 4000
_installed = False


def first_text(resp) -> str:
    """Text of the first text block (skips thinking / tool blocks)."""
    for block in getattr(resp, "content", None) or []:
        if getattr(block, "type", "") == "text":
            return block.text
    return ""


def install_fable_defaults():
    global _installed
    if _installed:
        return
    try:
        from anthropic.resources.messages import Messages
    except Exception:
        return
    original = Messages.create

    def create(self, *args, **kwargs):
        if str(kwargs.get("model", "")).startswith("claude-fable"):
            kwargs["max_tokens"] = min(max(int(kwargs.get("max_tokens") or 0) * 4, FABLE_MIN_MAX_TOKENS), 16000)
            body = dict(kwargs.get("extra_body") or {})
            cfg = dict(body.get("output_config") or {})
            cfg.setdefault("effort", FABLE_DEFAULT_EFFORT)
            body["output_config"] = cfg
            kwargs["extra_body"] = body
        return original(self, *args, **kwargs)

    Messages.create = create
    _installed = True


install_fable_defaults()
