from __future__ import annotations

import json
import logging
import random
import threading
from pathlib import Path
from typing import Final, List
from app.config.config import get_settings

settings = get_settings()
_RANGE_START = settings.providers.call_numbers_range_start
_RANGE_END   = settings.providers.call_numbers_range_end


logger = logging.getLogger(__name__)

_POOL_FILE: Final[Path] = Path(settings.providers.call_numbers_pool_file)


class CallNumberProvider:
    """
    CallNumberProvider manages a pool of unique 3-digit call numbers (201-500), ensuring each number is issued only once until the pool is exhausted.
    Attributes:
        _pool_path (Path): Path to the file storing the pool of available numbers.
        _lock (threading.Lock): Thread lock to ensure thread-safe access to the pool.
    Methods:
        __init__(pool_path: Path | str | None = None):
            Initializes the provider, setting up the pool file and ensuring the pool exists.
        get_number() -> str:
            Returns a unique 3-digit number from the pool, removing it from future availability.
            Raises RuntimeError if no numbers are left.
        _ensure_pool():
            Internal helper to create the pool file with all numbers if it does not exist.
        _load_pool() -> list[str]:
            Internal helper to load the current pool of numbers from the file.
        _save_pool(pool: list[str]):
            Internal helper to save the updated pool of numbers to the file.
    """
    

    def __init__(self, pool_path: Path | str | None = None):
        self._pool_path: Path = Path(pool_path) if pool_path else _POOL_FILE
        self._lock = threading.Lock()
        self._ensure_pool()

    # --------------------------------------------------
    # Public API
    # --------------------------------------------------
    def get_number(self) -> str:
        """Return a unique 3-digit number, removing it from the pool."""
        with self._lock:
            pool = self._load_pool()
            if not pool:
                raise RuntimeError("No call numbers left in the pool (201-500)")
            number = random.choice(pool)
            pool.remove(number)
            self._save_pool(pool)
            logger.info("CallNumberProvider issued number: %s (remaining=%d)", number, len(pool))
            return number

    # --------------------------------------------------
    # Internal helpers
    # --------------------------------------------------
    def _ensure_pool(self):
        if not self._pool_path.exists():
            pool: List[str] = [f"{i:03d}" for i in range(_RANGE_START, _RANGE_END + 1)]
            self._save_pool(pool)
            logger.info("CallNumberProvider created new pool with numbers %03d-%03d at %s",
            _RANGE_START, _RANGE_END, self._pool_path)

    def _load_pool(self) -> list[str]:
        with self._pool_path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def _save_pool(self, pool: list[str]):
        with self._pool_path.open("w", encoding="utf-8") as f:
            json.dump(pool, f, ensure_ascii=False)