# app/services/redis_store.py
from __future__ import annotations
from typing import Any, Dict, Optional
import contextvars
from redis.asyncio import Redis

# Kontext-Call-ID (damit patient_tools den Call zuordnen kann)
_current_call_id = contextvars.ContextVar("current_call_id", default=None)

def set_current_call_id(call_id: str) -> None:
    _current_call_id.set(call_id)

def get_current_call_id() -> Optional[str]:
    return _current_call_id.get()

_redis_client: Optional[Redis] = None

async def get_client(url: str) -> Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = Redis.from_url(url, encoding="utf-8", decode_responses=True)
        try:
            await _redis_client.ping()
        except Exception:
            # Redis down? Wir lassen die Pipeline trotzdem laufen.
            pass
    return _redis_client

def _key(prefix: str, call_id: str) -> str:
    return f"{prefix}{call_id}"

def _normalize(fields: Dict[str, Any]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for k, v in fields.items():
        if v is None:
            continue  # keine Felder mit None schreiben
        if isinstance(v, bool):
            out[k] = "true" if v else "false"
        else:
            out[k] = str(v)
    return out

async def write_initial_call(*, call_id: str, choosen_latency: Optional[float],
                             url: str, prefix: str, ttl_seconds: Optional[int]) -> None:
    r = await get_client(url)
    mapping = {
        "call_id": call_id,
        # genau dein Feldname:
        "choosen_latency": f"{choosen_latency:.3f}" if choosen_latency is not None else ""
    }
    await r.hset(_key(prefix, call_id), mapping=mapping)
    if ttl_seconds:
        await r.expire(_key(prefix, call_id), ttl_seconds)

async def update_patient_fields(*, call_id: str, url: str, prefix: str, ttl_seconds: Optional[int], **fields: Any) -> None:
    r = await get_client(url)
    mapping = _normalize(fields)
    if mapping:
        await r.hset(_key(prefix, call_id), mapping=mapping)
        if ttl_seconds:
            await r.expire(_key(prefix, call_id), ttl_seconds)