from __future__ import annotations

import secrets


def secure_compare(provided: str | None, expected: str | None) -> bool:
    if not provided or not expected:
        return False
    return secrets.compare_digest(provided, expected)
