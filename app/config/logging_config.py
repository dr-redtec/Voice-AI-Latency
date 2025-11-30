# logging_config.py
import logging, sys
from typing import Optional
from app.config.config import Settings

DEFAULT_FORMAT = "%(asctime)s | %(levelname)8s | %(name)s | %(message)s"

def setup_logging(settings: Settings,
                  level: Optional[str] = None,
                  format: str = DEFAULT_FORMAT) -> None:
    # Root
    logging.basicConfig(
        level=getattr(logging, (level or settings.__dict__.get("log_level", "INFO")).upper(), logging.INFO),
        format=format,
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,  # überschreibt evtl. frühere basicConfig
    )

    # Feineinstellungen wie bisher in main_ubu.py
    logging.getLogger("latency_injector").setLevel(logging.DEBUG)
    logging.getLogger("pipecat.processors.filters.stt_mute_filter").setLevel(logging.DEBUG)

    # Optionale Rauschkanäle runterdrehen:
    for noisy in ("asyncio", "aiohttp.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)