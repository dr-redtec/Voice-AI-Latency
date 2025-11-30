# stt_mute_setup.py
from pipecat.processors.filters.stt_mute_filter import (
    STTMuteFilter, STTMuteConfig, STTMuteStrategy,
)

def build_stt_mute(stt_service, latency_injector):
    """Erzeugt einen STTMuteFilter, der während Bot-Speech **und**
    der künstlichen Latenz jedes Nutzer-Audio blockiert."""

    async def should_mute_callback(flt):
        return flt._bot_is_speaking or latency_injector.busy

    return STTMuteFilter(
        stt_service=stt_service,               # ← **wichtig**
        config=STTMuteConfig(
            strategies={
                STTMuteStrategy.ALWAYS,        # Bot spricht
                STTMuteStrategy.CUSTOM,        # künstliche Latenz
            },
            should_mute_callback=should_mute_callback,
        ),
    )