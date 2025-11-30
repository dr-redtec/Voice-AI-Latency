from app.config.config import Settings
from pipecat.services.whisper.stt import WhisperSTTService, Model
from pipecat.transcriptions.language import Language

def build_stt(settings: Settings) -> WhisperSTTService:
    """
    Initializes and returns a WhisperSTTService instance using the provided settings.
    Args:
        settings (Settings): Configuration object containing STT model, device, compute type, no speech probability, and language.
    Returns:
        WhisperSTTService: An instance of the WhisperSTTService configured with the specified settings.
    """
    return WhisperSTTService(
        model=getattr(Model, settings.stt_model),
        device=settings.stt_device,
        compute_type=settings.stt_compute_type,
        no_speech_prob=settings.stt_no_speech_prob,
        language=Language[settings.stt_language],
    )