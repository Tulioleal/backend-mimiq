from __future__ import annotations

from core.config import Settings
from core.security import secure_compare


class AuthService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def is_authorized(self, candidate: str | None) -> bool:
        return secure_compare(candidate, self.settings.x_admin_key)
