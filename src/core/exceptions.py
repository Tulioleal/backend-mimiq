from __future__ import annotations

from models.gpu import GPUStatusRead


class ConfigurationError(RuntimeError):
    pass


class GPUNotReadyError(RuntimeError):
    def __init__(self, status: GPUStatusRead):
        super().__init__(status.detail or "GPU instance is not ready")
        self.status = status


class UpstreamTTSError(RuntimeError):
    pass
