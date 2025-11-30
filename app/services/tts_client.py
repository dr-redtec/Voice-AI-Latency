from typing import Optional
import aiohttp
from app.config.config import Settings
from app.services.piper_v1_tts import PiperV1TTSService


# OpenAI-TTS aus Pipecat
from pipecat.services.openai.tts import OpenAITTSService  # voices inkl. "nova" (24 kHz)  # noqa
from pipecat.services.azure.tts import AzureTTSService, AzureBaseTTSService
from pipecat.transcriptions.language import Language
import os


def build_tts(settings: Settings, session: Optional[aiohttp.ClientSession] = None):
    """
    Liefert je nach settings.tts_provider entweder Piper oder OpenAI TTS.
    Move-only: keine Pipeline-Logikänderung.
    """
    if settings.tts_provider == "openai":
        # OpenAI TTS (gpt-4o-mini-tts, voice "nova")
        # api_key: nimmt OPENAI_API_KEY aus ENV, falls None
        return OpenAITTSService(
            api_key=settings.openai_api_key or None,
            voice=settings.openai_tts_voice,
            model=settings.openai_tts_model,
            sample_rate=24000,   # OpenAI TTS ist 24kHz; Pipecat setzt’s intern auch so
        )
    if settings.tts_provider == "azure":
        params = AzureBaseTTSService.InputParams(
            language=Language.DE_DE,
            role=settings.azure_tts_role,
            style=settings.azure_tts_style,
            style_degree="1,5",
        )
        return AzureTTSService(
            api_key=settings.azure_speech_key,
            region=settings.azure_speech_region,      # <— nur der Kurzname!
            voice=settings.azure_tts_voice,
            params=params,
        )
    # Default: Piper (dein bestehender Client)
    return PiperV1TTSService(
        base_url=settings.tts_base_url,
        sample_rate=settings.tts_sample_rate,
        voice=settings.tts_voice,
        aiohttp_session=session,
    )
