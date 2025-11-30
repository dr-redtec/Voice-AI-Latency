#
# Copyright (c) 2024–2025
# SPDX-License-Identifier: BSD-2-Clause
#
# Azure Communication Services ↔ Pipecat frame serializer (v0.0.73)
 
import audioop
import base64
import json
from typing import Optional
 
# from loguru import logger
from pydantic import BaseModel
 
from pipecat.frames.frames import (
    AudioRawFrame,
    CancelFrame,
    EndFrame,
    Frame,
    InputAudioRawFrame,
    StartFrame,
    StartInterruptionFrame,
    TransportMessageFrame,
    TransportMessageUrgentFrame,
)
from pipecat.serializers.base_serializer import FrameSerializer, FrameSerializerType
 
# ───────────────────────────────────────────────────────────────────────────────
 
 
class ACSFrameSerializer(FrameSerializer):
    """
    Handles ACS Media Streaming WebSocket envelopes:
        {"kind":"audioData","audioData":{...}}
        {"kind":"stopAudio","stopAudio":{}}
 
    • Converts AudioRawFrame ⇄ JSON
    • Resamples 8-kHz PCM to 16-kHz if necessary
    """
 
    class InputParams(BaseModel):
        sample_rate: int = 16_000       # pipeline SR
        auto_stop_audio: bool = True    # emit StopAudio on interrupt/end
 
    def __init__(self, params: Optional["ACSFrameSerializer.InputParams"] = None):
        self._params = params or ACSFrameSerializer.InputParams()
        self._sample_rate = self._params.sample_rate
 
    # -------------------------------------------------------------------------
    #  Mandatory overrides
    # -------------------------------------------------------------------------
    @property
    def type(self) -> FrameSerializerType:
        return FrameSerializerType.TEXT
 
    async def setup(self, frame: StartFrame):
        #  Use the real input SR if the pipeline overrides it
        self._sample_rate = frame.audio_in_sample_rate or self._sample_rate
 
    # -------------------- Pipecat → ACS --------------------------------------
    async def serialize(self, frame: Frame) -> str | bytes | None:
        if isinstance(frame, (EndFrame, CancelFrame, StartInterruptionFrame)):
            if self._params.auto_stop_audio:
                return json.dumps({"kind": "stopAudio", "stopAudio": {}})
            return None
 
        elif isinstance(frame, AudioRawFrame):
            pcm = frame.audio
            sr  = frame.sample_rate or self._sample_rate
 
            # we keep 16-kHz little-endian PCM exactly as ACS likes it
            if sr != 16_000:
                # down/up-sample to 16 kHz linear PCM, 1 channel, 2 bytes/sample
                pcm, _ = audioop.ratecv(pcm, 2, 1, sr, 16_000, None)
                sr = 16_000
 
            payload = base64.b64encode(pcm).decode()
            envelope = {
                "kind": "audioData",
                "audioData": {
                    "timestamp": None,            # let ACS ignore / fill
                    "participantRawID": "",       # optional
                    "data": payload,
                    "silent": False,
                    "sampleRate": sr,
                },
            }
            return json.dumps(envelope)
 
        elif isinstance(frame, (TransportMessageFrame, TransportMessageUrgentFrame)):
            return json.dumps(frame.message)
 
        return None  # other frame types we simply drop
 
    # -------------------- ACS → Pipecat --------------------------------------
    async def deserialize(self, data: str | bytes) -> Frame | None:
        try:
            msg = json.loads(data)
        except ValueError:
            return None
 
        kind = msg.get("kind") or msg.get("Kind")
        if kind != "AudioData":
            return None
 
        audio = msg.get("audioData") or msg.get("AudioData") or {}
        b64   = audio.get("data") or audio.get("Data")
        if not b64:
            return None
 
        pcm = base64.b64decode(b64)
        sr  = audio.get("sampleRate") or audio.get("SampleRate") or 16_000
 
        # up-sample PSTN (8 kHz) to 16 kHz so Whisper is happy
        if sr != self._sample_rate:
            pcm, _ = audioop.ratecv(pcm, 2, 1, sr, self._sample_rate, None)
 
        return InputAudioRawFrame(audio=pcm, num_channels=1, sample_rate=self._sample_rate)