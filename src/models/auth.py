from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    admin_key: str = Field(min_length=1, alias="adminKey")


class SessionResponse(BaseModel):
    authenticated: bool


class WebSocketTicketResponse(BaseModel):
    ticket: str
    expires_in_seconds: int = Field(alias="expiresInSeconds")
