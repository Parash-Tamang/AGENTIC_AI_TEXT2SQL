from typing import Callable

"""Token counting helper with graceful fallback.

Centralizes optional dependency handling for `tiktoken` so node modules
do not contain conditional imports.
"""
try:
    import tiktoken as _tiktoken

    def count_tokens(text: str, model: str = "gpt-4") -> int:
        try:
            enc = _tiktoken.encoding_for_model(model)
        except KeyError:
            enc = _tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))

except Exception:

    def count_tokens(text: str, model: str = "gpt-4") -> int:  # type: ignore[misc]
        # Fallback heuristic when tiktoken is not installed.
        return len(text) // 4


__all__ = ["count_tokens"]
