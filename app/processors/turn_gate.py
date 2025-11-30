# app/turn_gate.py
import logging
from pipecat.frames.frames import (
    # Audio & User Speech Frames
    InputAudioRawFrame, UserAudioRawFrame,
    UserStoppedSpeakingFrame, UserStartedSpeakingFrame,
    # Bot Speech Frames
    # BotStartedSpeakingFrame,  # <- nicht mehr genutzt
    BotStoppedSpeakingFrame,
    # Basis
    Frame,
)
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection


class TurnGateProcessor(FrameProcessor):
    """
    A processor that manages audio frame flow based on user and bot speaking events,
    implementing a "turn gate" mechanism to mute/unmute audio streams according to conversation state.
    Attributes:
        _enabled (bool): Indicates if the gate is active. When disabled, all frames pass through.
        _mute (bool): Current mute state; when True, incoming audio frames are dropped.
        _dropped (int): Counter for the number of dropped audio frames while muted.
        _saw_user_since_enable (bool): Tracks if user speech has occurred since the gate was enabled.
        logger (logging.Logger): Logger for status and debug messages.
    Methods:
        enable():
            Activates the gate, resets mute state and statistics.
        disable():
            Deactivates the gate, resets mute state and statistics, allows all frames through.
        async process_frame(frame: Frame, direction: FrameDirection):
            Processes incoming frames according to the turn-taking state machine:
                - Mutes audio when the user stops speaking (after user speech detected).
                - Unmutes audio when the bot finishes speaking.
                - Drops audio frames while muted.
                - Passes all other frames through.
    """

    def __init__(self, *, log_level: int = logging.INFO):
        super().__init__()
        self._enabled = True          # neu: Gate kann an/aus sein
        self._mute = False            # aktueller Zustand
        self._dropped = 0             # Statistik
        self._saw_user_since_enable = False  # neu: Entprellung für late UserStopped

        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(log_level)
        if not logging.getLogger().handlers:
            logging.basicConfig(
                level=log_level,
                format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            )

    # optional public API
    def enable(self):
        self._enabled = True
        self._mute = False
        self._dropped = 0
        self._saw_user_since_enable = False

    def disable(self):
        # beim Deaktivieren alles durchlassen und State zurücksetzen
        self._enabled = False
        self._mute = False
        self._dropped = 0
        self._saw_user_since_enable = False

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)   # Pflicht-Boilerplate

        # Wenn disabled: nichts am Zustand ändern, alles durchlassen
        if not self._enabled:
            await self.push_frame(frame, direction)
            return

        # ---------- State-Machine ---------------------------------------
        if isinstance(frame, UserStartedSpeakingFrame):
            # markiert, dass "UserStopped" nach dem Enable wieder gültig ist
            self._saw_user_since_enable = True

        elif isinstance(frame, UserStoppedSpeakingFrame):
            # nur reagieren, wenn seit dem letzten Enable auch wirklich User-Speech lief
            if self._saw_user_since_enable:
                if not self._mute:
                    self.logger.info("🎤  TurnGate MUTE ON – Eingehende Audio-Frames werden verworfen")
                self._mute = True
                self._dropped = 0

        # WICHTIG: Unmute erst wenn der Bot fertig ist, nicht beim Start!
        elif isinstance(frame, BotStoppedSpeakingFrame):
            if self._mute:
                self.logger.info("🗣️  TurnGate MUTE OFF – %d Frames verworfen", self._dropped)
            self._mute = False
            # nach einem vollständigen Bot-Turn ist die nächste UserStopped wieder "gültig"
            self._saw_user_since_enable = False

        # ---------- Audio-Frames ggf. droppen ---------------------------
        if self._mute and isinstance(frame, (InputAudioRawFrame, UserAudioRawFrame)):
            self._dropped += 1
            return  # Frame wird *nicht* weitergereicht

        # ---------- alles andere normal durchlassen ---------------------
        await self.push_frame(frame, direction)
