# app/services/container.py
from dataclasses import dataclass
from typing import Optional
import aiohttp

from app.config.config import Settings
from app.services.llm_client import build_llm
from app.services.stt_client import build_stt
from app.services.tts_client import build_tts

# Typen (optional, nur für bessere Hints)
from pipecat.services.azure.llm import AzureLLMService
from pipecat.services.whisper.stt import WhisperSTTService
from app.services.piper_v1_tts import PiperV1TTSService


@dataclass
class Services:
    stt: WhisperSTTService
    llm: AzureLLMService
    tts: PiperV1TTSService


def make_services(settings: Settings, session: Optional[aiohttp.ClientSession] = None) -> Services:
    """
    Creates and returns a Services object composed of STT, LLM, and TTS services.
    Args:
        settings (Settings): Configuration settings for building the services.
        session (Optional[aiohttp.ClientSession], optional): An optional aiohttp client session for TTS service. Defaults to None.
    Returns:
        Services: An object containing initialized STT, LLM, and TTS services.
    """
    

    stt = build_stt(settings)
    llm = build_llm(settings)
    tts = build_tts(settings, session=session)
    return Services(stt=stt, llm=llm, tts=tts)
