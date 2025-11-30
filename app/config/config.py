# config.py
from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List, Literal
from typing import Optional


class RedisSettings(BaseSettings):
    url: str = Field("redis://localhost:6379/0", env="REDIS_URL")
    key_prefix: str = Field("voiceai:call:", env="REDIS_KEY_PREFIX")
    ttl_seconds: Optional[int] = Field(None, env="REDIS_TTL_SECONDS")  # None => kein TTL


class LatencySettings(BaseSettings):
    """
    Configuration settings for latency management.
    Attributes:
        strategy (Literal["round_robin"]): The strategy used for latency handling. Defaults to "round_robin".
        choices_s (List[float]): List of latency choices in seconds. Defaults to [1.0, 4.0, 8.0].
    """
    strategy: Literal["round_robin"] = "round_robin"
    choices_s: List[float] = [3.0, 7.0, 0.1]

class SlotSettings(BaseSettings):
    """
    SlotSettings defines configuration options for slot scheduling.
    Attributes:
        weeks_ahead (int): Number of weeks ahead to consider for slot scheduling. Default is 4.
        var_within_days (int): Number of days within which slot variations are allowed. Default is 7.
        var_max_n (int): Maximum number of slot variations permitted. Default is 5.
    """
    
    weeks_ahead: int = 4
    var_within_days: int = 7
    var_max_n: int = 2

class ProvidersSettings(BaseSettings):
    """
    ProvidersSettings defines configuration settings for provider-related options.
    Attributes:
        call_numbers_pool_file (str): Path to the JSON file containing the pool of call numbers.
    """
    
    call_numbers_pool_file: str = "app/assets/call_numbers.json"
    call_numbers_range_start: int = Field(501, validation_alias="CALL_NUMBERS_RANGE_START")
    call_numbers_range_end: int = Field(800, validation_alias="CALL_NUMBERS_RANGE_END")

class TelephonySettings(BaseSettings):
    # Verzögerung vor dem Answer in Sekunden (für 1–2 "Piepen")
    ring_delay_s: float = 2.0

class Settings(BaseSettings):
    """
    Settings configuration class for the Voice AI Latency V2 application.
    This class manages environment-based configuration for various services and components, including:
    Attributes:
        acs_connection_string (str): Azure Communication Services connection string.
        acs_public_base (str): Base URL for ACS callbacks.
        acs_phone_number (str): ACS phone number for outbound calls.
        media_stream_transport_url (str): URL for media streaming transport between ACS and WebSocket.
        azure_openai_endpoint (str): Endpoint for Azure OpenAI service.
        azure_openai_key (str): API key for Azure OpenAI service.
        azure_openai_model (str): Deployment model name for Azure OpenAI.
        azure_openai_api_version (Optional[str]): API version for Azure OpenAI deployment.
        llm_temperature (float): Temperature setting for language model responses.
        llm_max_tokens (int): Maximum number of tokens for language model responses.
        stt_model (str): Whisper STT model name.
        stt_device (str): Device for STT inference (e.g., "cuda").
        stt_compute_type (str): Compute type for STT inference.
        stt_no_speech_prob (float): Probability threshold for no speech detection.
        stt_language (str): Language code for STT.
        ws_audio_in_sample_rate (int): Input audio sample rate for WebSocket.
        ws_audio_out_sample_rate (int): Output audio sample rate for WebSocket.
        ws_session_timeout (int): Session timeout for WebSocket connections (seconds).
        tts_base_url (str): Base URL for TTS service.
        tts_sample_rate (int): Sample rate for TTS audio output.
        tts_voice (str): Voice identifier for TTS.
        enable_tracing (bool): Enable OpenTelemetry tracing.
        otel_endpoint (str): OpenTelemetry exporter endpoint.
        otel_service_name (str): Service name for OpenTelemetry.
        otel_console_export (bool): Enable console export for OpenTelemetry.
        host (str): Server host address.
        port (int): Server port.
        latency (LatencySettings): Latency configuration settings.
        slots (SlotSettings): Slot configuration settings.
        providers (ProvidersSettings): Provider configuration settings.
    Methods:
        make_callback_url(caller_id: str) -> str:
            Constructs the callback URL for ACS events using the provided caller ID.
    Configuration:
        Loads environment variables from the ".env" file and ignores extra fields.
    """
    

    # --- Azure Communication Services (ACS) ---
    acs_connection_string: str = Field(..., validation_alias="ACS_CONNECTION_STRING")
    acs_public_base: str       = Field(..., validation_alias="ACS_PUBLIC_BASE")  # für callback_url
    acs_phone_number: str      = Field(..., validation_alias="ACS_PHONE_NUMBER")

    # Media Streaming (ACS <-> WS Transport)
    media_stream_transport_url: str = Field(..., validation_alias="MEDIA_STREAM_TRANSPORT_URL")

    # --- Azure OpenAI ---
    azure_openai_endpoint: str   = Field(..., validation_alias="AZURE_OPENAI_SERVICE_ENDPOINT")
    azure_openai_key: str        = Field(..., validation_alias="AZURE_OPENAI_SERVICE_KEY")
    azure_openai_model: str      = Field(..., validation_alias="AZURE_OPENAI_DEPLOYMENT_MODEL_NAME")
    azure_openai_api_version: str|None = Field(None, validation_alias="AZURE_OPENAI_DEPLOYMENT_VERSION")
    llm_temperature: float = 0.1
    llm_max_tokens: int = 1000

    # --- Whisper STT (Pipecat) ---
    stt_model: str        = "LARGE_V3_TURBO"
    stt_device: str       = "cuda"
    stt_compute_type: str = "float16"
    stt_no_speech_prob: float = 0.3
    stt_language: str     = "DE"

    # --- WebSocket / Audio IO ---
    ws_audio_in_sample_rate: int  = 16_000
    ws_audio_out_sample_rate: int = 16_000
    ws_session_timeout: int       = 300

    # --- TTS (Piper v1) ---
        # TTS-Provider-Auswahl
    tts_provider: Literal["piper", "openai", "azure"] = "azure"

    
    # Azure Speech (Cognitive Services)
    azure_speech_key: str | None = None
    azure_speech_region: str | None = None

    # Azure-Voice & Optionen (Beispiele)
    azure_tts_voice: str = "de-DE-SeraphinaMultilingualNeural"  # oder jede andere Neural Voice

    # optionale Prosodie/Style-Parameter (werden unten gezeigt)
    azure_tts_role: str | None = None
    azure_tts_style: str | None = "friendly"

    # Piper (dein bestehender Client
    tts_base_url: str   = "http://localhost:5005"
    tts_sample_rate: int = 16_000
    # tts_voice: str       = "de_DE-ramona-low"
    tts_voice: str       = "de_DE-kerstin-low"

    # tts_sample_rate: int = 22_050
    # tts_voice: str       = "de_DE-thorsten-high"

    # OpenAI-TTS (via Pipecat)
    openai_api_key: str | None = None              # optional; sonst kommt er aus ENV
    openai_tts_model: str = "gpt-4o-mini-tts"      # Default laut Pipecat-Doku
    openai_tts_voice: str = "nova"                 # <— gewünschte Stimme

    # --- Tracing / OTEL ---
    enable_tracing: bool = Field(False, validation_alias="ENABLE_TRACING")
    otel_endpoint: str   = Field("http://localhost:4317", validation_alias="OTEL_EXPORTER_OTLP_ENDPOINT")
    otel_service_name: str = Field("voice_ai_latency_v2", validation_alias="OTEL_SERVICE_NAME")
    otel_console_export: bool = Field(False, validation_alias="OTEL_CONSOLE_EXPORT")

    # --- Server ---
    host: str = "0.0.0.0"
    port: int = Field(8765, validation_alias="PORT")


    # --- Sonstiges ---
    latency: LatencySettings = LatencySettings()
    slots: SlotSettings = SlotSettings()
    providers: ProvidersSettings = ProvidersSettings()
    telephony_conf: TelephonySettings = TelephonySettings()
    redis: RedisSettings = RedisSettings()
    # Prompt-Auswahl
    system_prompt_name: str = Field("german_voice_agent_appointment", description="Name des Systemprompts aus SYSTEM_PROMPTS")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Hilfs-Property für callback_url
    def make_callback_url(self, caller_id: str) -> str:
        return f"{self.acs_public_base}/acs-events/?call_id={caller_id}"

@lru_cache
def get_settings() -> Settings:
    return Settings()