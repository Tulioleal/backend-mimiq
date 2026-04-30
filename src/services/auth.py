from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from core.config import Settings
from core.security import secure_compare


@dataclass(slots=True)
class WebSocketTicket:
    expires_at: datetime
    purpose: str
    used: bool = False


class AuthService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._ws_tickets: dict[str, WebSocketTicket] = {}

    def is_authorized(self, candidate: str | None) -> bool:
        return secure_compare(candidate, self.settings.x_admin_key)

    def issue_ws_ticket(self, purpose: str = "generation_stream", ttl_seconds: int = 60) -> str:
        self._prune_ws_tickets()
        ticket = secrets.token_urlsafe(32)
        self._ws_tickets[self._hash_ticket(ticket)] = WebSocketTicket(
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds),
            purpose=purpose,
        )
        return ticket

    def consume_ws_ticket(self, ticket: str | None, purpose: str = "generation_stream") -> bool:
        if not ticket:
            return False

        self._prune_ws_tickets()
        ticket_hash = self._hash_ticket(ticket)
        stored = self._ws_tickets.get(ticket_hash)
        if stored is None or stored.used or stored.purpose != purpose:
            return False
        if stored.expires_at <= datetime.now(timezone.utc):
            self._ws_tickets.pop(ticket_hash, None)
            return False

        stored.used = True
        return True

    def _prune_ws_tickets(self) -> None:
        now = datetime.now(timezone.utc)
        expired = [ticket_hash for ticket_hash, ticket in self._ws_tickets.items() if ticket.expires_at <= now]
        for ticket_hash in expired:
            self._ws_tickets.pop(ticket_hash, None)

    def _hash_ticket(self, ticket: str) -> str:
        return hashlib.sha256(ticket.encode("utf-8")).hexdigest()
