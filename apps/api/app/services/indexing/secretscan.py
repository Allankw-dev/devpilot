"""Spotting text that looks like a credential, so it is never stored or sent to an AI model.

This is a safety net, not a guarantee: it catches well-known token formats and obvious
`password = "..."` assignments. A chunk that matches is skipped entirely.
"""

import re

_PATTERNS = [
    re.compile(r"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY(?: BLOCK)?-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),  # AWS access key id
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}\b"),  # GitHub tokens
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{40,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"),  # Google API key
    re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}"),  # Anthropic
    re.compile(r"\bsk-[A-Za-z0-9]{32,}\b"),  # OpenAI-style
    re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}"),  # Slack
    re.compile(r"\b[sr]k_live_[A-Za-z0-9]{20,}\b"),  # Stripe live keys
    re.compile(r"\bSG\.[A-Za-z0-9_\-]{16,}\.[A-Za-z0-9_\-]{16,}\b"),  # SendGrid
    re.compile(
        r"""(?ix)
        (?:password|passwd|secret|api[_-]?key|access[_-]?key|auth[_-]?token|private[_-]?key)
        ["']?\s*[:=]\s*["'][^"'\s]{20,}["']
        """
    ),
]


def contains_secret(text: str) -> bool:
    return any(p.search(text) for p in _PATTERNS)
