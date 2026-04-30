from __future__ import annotations

from dataclasses import dataclass

from httpx import AsyncClient

from core.config import Settings
from services.auth import AuthService
from services.audio_health import AudioHealthAnalyzer
from services.generation_service import GenerationService
from services.github_actions import GitHubActionsService
from services.gpu import GPUOrchestrator
from services.llm import LLMPreprocessor
from services.storage import StorageService
from services.tts_runtime_state import TTSRuntimeStateService
from services.tts_proxy import TTSProxyService
from services.voice_service import VoiceCandidateService, VoiceService


@dataclass(slots=True)
class AppServices:
    auth: AuthService
    audio_health: AudioHealthAnalyzer
    storage: StorageService
    llm: LLMPreprocessor
    gpu: GPUOrchestrator
    tts_runtime_state: TTSRuntimeStateService
    voices: VoiceService
    voice_candidates: VoiceCandidateService
    generations: GenerationService
    tts_proxy: TTSProxyService


def build_services(settings: Settings, http_client: AsyncClient) -> AppServices:
    auth = AuthService(settings)
    storage = StorageService(settings)
    llm = LLMPreprocessor(settings, http_client)
    github_actions = GitHubActionsService(settings, http_client)
    tts_runtime_state = TTSRuntimeStateService()
    gpu = GPUOrchestrator(settings, http_client, tts_runtime_state, github_actions)
    voices = VoiceService()
    voice_candidates = VoiceCandidateService()
    generations = GenerationService()
    return AppServices(
        auth=auth,
        audio_health=AudioHealthAnalyzer(),
        storage=storage,
        llm=llm,
        gpu=gpu,
        tts_runtime_state=tts_runtime_state,
        voices=voices,
        voice_candidates=voice_candidates,
        generations=generations,
        tts_proxy=TTSProxyService(settings, llm, storage, gpu, voices, generations),
    )
