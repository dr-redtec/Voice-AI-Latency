from __future__ import annotations

import asyncio
import itertools
import logging
import random
from typing import Iterable, Sequence

from pipecat.frames.frames import (
    Frame,
    LLMMessagesFrame,
    STTMuteFrame,                # ⬅️ wichtig
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContextFrame
from pipecat.frames.frames import StopFrame, StartFrame, TTSSpeakFrame
from app.config.config import get_settings

settings = get_settings()

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────
# Konfiguration
# ──────────────────────────────────────────────────────────────────────
LATENCY_CHOICES: Sequence[float] = tuple(settings.latency.choices_s)
_latency_cycle = itertools.cycle(LATENCY_CHOICES)           # für round-robin

def _next_latency_round_robin() -> float:
    return next(_latency_cycle)

# ──────────────────────────────────────────────────────────────────────
# Frame-Processor
# ──────────────────────────────────────────────────────────────────────
class LatencyInjector(FrameProcessor):
    """
    LatencyInjector is a FrameProcessor that introduces artificial latency into the processing of downstream frames,
    simulating delayed responses in a voice AI pipeline. It supports configurable latency strategies ("random" or "round_robin")
    and manages muting/unmuting of upstream STT (speech-to-text) frames during the latency period.
    Args:
        choices (Iterable[float] | None): Optional sequence of latency values (in seconds) to choose from.
        strategy (str): Latency selection strategy, either "random" or "round_robin". Defaults to "random".
    Attributes:
        busy (bool): Indicates whether the latency pause is currently active.
        latency_seconds (float | None): The currently selected latency value in seconds.
    Methods:
        process_frame(frame, direction): Main hook for processing frames, injecting latency and managing STT mute/unmute.
    """
    

    def __init__(
        self,
        choices: Iterable[float] | None = None,
        *,
        strategy: str = "random",            # "random" | "round_robin"
    ):
        super().__init__()

        self._choices: Sequence[float] = (
            tuple(choices) if choices else LATENCY_CHOICES
        )
        if strategy not in {"random", "round_robin"}:
            raise ValueError("strategy must be 'random' or 'round_robin'")
        self._strategy = strategy

        self._latency_seconds: float | None = None
        self._busy: bool = False             # extern abfragbar

    # ── Helper ────────────────────────────────────────────────────────
    async def _pick_latency(self) -> float:
        if self._latency_seconds is None:
            if self._strategy == "random":
                self._latency_seconds = random.choice(self._choices)
            else:                              # round-robin
                self._latency_seconds = _next_latency_round_robin()

            logger.info(
                "LatencyInjector picked latency (strategy=%s): %.2f s",
                self._strategy,
                self._latency_seconds,
            )
        return self._latency_seconds

    # ── Haupt-Hook ────────────────────────────────────────────────────
    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        # 1️⃣  Erster Downstream-Frame eines User-Turns
        if (
            direction is FrameDirection.DOWNSTREAM
            and isinstance(frame, (OpenAILLMContextFrame, LLMMessagesFrame))
        ):
            await self.push_frame(STTMuteFrame(mute=True), FrameDirection.UPSTREAM)
            self._busy = True
            logger.debug("LatencyInjector busy, muting STT")

            latency = await self._pick_latency()
            logger.debug("LatencyInjector sleeping %.2f s …", latency)
            await asyncio.sleep(latency)

            # ⚠️  KEIN Unmute hier!

        # 2️⃣  Erst wenn der Bot zu sprechen beginnt …
        if (
            self._busy
            and direction is FrameDirection.DOWNSTREAM
            and isinstance(frame, TTSSpeakFrame)
        ):
            await self.push_frame(STTMuteFrame(mute=False), FrameDirection.UPSTREAM)
            logger.debug("LatencyInjector unmuting STT")
            self._busy = False

        # Original-Frame immer weiterleiten
        await self.push_frame(frame, direction)

    # ── Properties ───────────────────────────────────────────────────
    @property
    def busy(self) -> bool:
        """`True`, solange die Latenz-Pause aktiv ist."""
        return self._busy

    @property
    def latency_seconds(self) -> float | None:
        return self._latency_seconds