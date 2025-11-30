from __future__ import annotations

import json
from typing import Any, AsyncGenerator, Dict, Optional

import aiohttp
from loguru import logger
from pipecat.frames.frames import (
    ErrorFrame,
    Frame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
)
from pipecat.services.piper.tts import PiperTTSService
from pipecat.utils.tracing.service_decorators import traced_tts


class PiperV1TTSService(PiperTTSService):
    """Adapter für den neuen Piper v1-HTTP-Server."""

    def __init__(
        self,
        *,
        base_url: str,
        aiohttp_session: aiohttp.ClientSession,
        sample_rate: Optional[int] = None,
        voice: Optional[str] = None,
        speaker: Optional[str] = None,
        speaker_id: Optional[int] = None,
        synthesis_params: Optional[Dict[str, Any]] = None,
        **kwargs,
    ):
        """
        Args
        ----
        base_url:
            Basis-URL des Piper v1-HTTP-Servers, z. B. ``http://localhost:5000``.
        aiohttp_session:
            Gemeinsame :class:`aiohttp.ClientSession`.
        sample_rate:
            Ziel-Samplerate; wenn ``None``, wird die von Piper gesendet –
            Pipecat interpoliert gegebenenfalls.
        voice / speaker / speaker_id:
            Entspricht den JSON-Feldern der Piper-API
            (``speaker_id`` hat Vorrang vor ``speaker``).
        synthesis_params:
            Beliebige weitere Felder, z. B. ``{"length_scale": 1.1}``.
        """
        super().__init__(
            base_url=base_url,
            aiohttp_session=aiohttp_session,
            sample_rate=sample_rate,
            **kwargs,
        )

        self._voice = voice
        self._speaker = speaker
        self._speaker_id = speaker_id
        self._synthesis_params = synthesis_params or {}

        # für Metrics/Config-Dump o. Ä.
        self._settings.update(
            {
                "voice": voice,
                "speaker": speaker,
                "speaker_id": speaker_id,
                **self._synthesis_params,
            }
        )

    # --------------------------------------------------------------------- #
    # TTS                                                                    #
    # --------------------------------------------------------------------- #

    @traced_tts
    async def run_tts(self, text: str) -> AsyncGenerator[Frame, None]:
        """Erzeugt Audioframes aus *text* über den Piper v1-Server."""

        logger.debug(f"{self}: Generating TTS [{text!r}]")

        # ---- Request vorbereiten ---------------------------------------- #
        payload: Dict[str, Any] = {"text": text}
        if self._voice:
            payload["voice"] = self._voice
        if self._speaker_id is not None:
            payload["speaker_id"] = self._speaker_id
        elif self._speaker:
            payload["speaker"] = self._speaker
        if self._synthesis_params:
            payload.update(self._synthesis_params)

        headers = {"Content-Type": "application/json"}

        # ---- HTTP-Roundtrip --------------------------------------------- #
        try:
            await self.start_ttfb_metrics()
            async with self._session.post(
                self._base_url, json=payload, headers=headers
            ) as response:
                if response.status != 200:
                    error = await response.text()
                    logger.error(
                        "%s error getting audio (status: %s, error: %s)",
                        self,
                        response.status,
                        error,
                    )
                    yield ErrorFrame(
                        f"Error getting audio (status: {response.status}, "
                        f"error: {error})"
                    )
                    return

                await self.start_tts_usage_metrics(text)
                CHUNK_SIZE = self.chunk_size

                yield TTSStartedFrame()

                async for chunk in response.content.iter_chunked(CHUNK_SIZE):
                    # Piper liefert WAV – Header einmalig entfernen
                    if chunk.startswith(b"RIFF"):
                        chunk = chunk[44:]
                    if chunk:
                        await self.stop_ttfb_metrics()
                        yield TTSAudioRawFrame(chunk, self.sample_rate, 1)

        except Exception as exc:  # pragma: no cover
            logger.exception("Error in run_tts: %s", exc)
            yield ErrorFrame(error=str(exc))

        finally:
            logger.debug(f"{self}: Finished TTS [{text!r}]")
            await self.stop_ttfb_metrics()
            yield TTSStoppedFrame()