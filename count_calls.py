#!/usr/bin/env python3
"""
count_calls.py — Zähle Voice-AI-Call-Einträge in Redis.

Zählt standardmäßig alle Keys mit einem Prefix (default: voiceai:call:).
Optional kannst du mit --where Feld=wert filtern (UND-Verknüpfung).

Nutzung:
  python count_calls.py
  python count_calls.py --where is_complete=true
  python count_calls.py --where slot_confirmed=true --where last_name=Müller
  python count_calls.py --redis-url redis://localhost:6379/0 --prefix voiceai:call:

ENV-Variablen (optional):
  REDIS_URL         (default: redis://localhost:6379/0)
  REDIS_KEY_PREFIX  (default: voiceai:call:)
"""

import os
import argparse
import asyncio
from typing import Dict, Any, List, Tuple
from redis.asyncio import Redis

DEFAULT_REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
DEFAULT_PREFIX = os.getenv("REDIS_KEY_PREFIX", "voiceai:call:")

# Reihenfolge nur für lesbarere Debug-Ausgaben (nicht zwingend nötig)
PREFERRED_ORDER = [
    "call_id",
    "choosen_latency",
    "first_name",
    "last_name",
    "phone",
    "visit_reason",
    "chosen_slot",
    "slot_confirmed",
    "is_complete",
]

def _coerce_stored_value(key: str, v: str) -> Any:
    """Konvertiere Strings aus Redis in passende Python-Typen."""
    if v == "":
        return None
    lv = v.lower()
    if lv in ("true", "false"):
        return lv == "true"
    if key == "choosen_latency":
        try:
            return float(v)
        except ValueError:
            return v
    return v

def _coerce_query_value(v: str) -> Any:
    """Konvertiert CLI-Werte grob in passende Typen (true/false -> bool, Zahl -> float, sonst String)."""
    lv = v.lower()
    if lv in ("true", "false"):
        return lv == "true"
    try:
        return float(v)
    except ValueError:
        return v

def _parse_where(items: List[str]) -> List[Tuple[str, Any]]:
    """Parst --where Feld=Wert in Tupel-Liste und coerct Werte."""
    pairs: List[Tuple[str, Any]] = []
    for it in items or []:
        if "=" not in it:
            raise ValueError(f"--where erwartet 'feld=wert', bekommen: {it!r}")
        k, v = it.split("=", 1)
        pairs.append((k.strip(), _coerce_query_value(v.strip())))
    return pairs

async def count_keys(redis_url: str, prefix: str) -> int:
    r = Redis.from_url(redis_url, encoding="utf-8", decode_responses=True)
    n = 0
    async for _ in r.scan_iter(f"{prefix}*"):
        n += 1
    return n

async def count_keys_where(redis_url: str, prefix: str, where: List[Tuple[str, Any]]) -> int:
    """Zähle nur Keys, deren Hash-Felder exakt den where-Bedingungen entsprechen (UND)."""
    r = Redis.from_url(redis_url, encoding="utf-8", decode_responses=True)
    matches = 0
    async for key in r.scan_iter(f"{prefix}*"):
        fields = [k for k, _ in where]
        # hole genau die benötigten Felder
        values = await r.hmget(key, fields)
        # mappe in Dict und coerce gespeicherte Werte
        d: Dict[str, Any] = {}
        for (k, _), v in zip(where, values):
            if v is None:
                d[k] = None
            else:
                d[k] = _coerce_stored_value(k, v)
        # prüfe Gleichheit aller Bedingungen
        ok = all(d[k] == target for (k, target) in where)
        if ok:
            matches += 1
    return matches

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Zählt Call-Keys in Redis (optional mit Filtern).")
    p.add_argument("--redis-url", default=DEFAULT_REDIS_URL, help=f"Redis URL (default: {DEFAULT_REDIS_URL})")
    p.add_argument("--prefix", default=DEFAULT_PREFIX, help=f"Key-Prefix (default: {DEFAULT_PREFIX})")
    p.add_argument(
        "--where",
        action="append",
        help="Filter im Format feld=wert (mehrfach möglich, UND-Verknüpfung). z. B. is_complete=true",
    )
    return p.parse_args()

def main():
    args = parse_args()
    where = _parse_where(args.where or [])
    if not where:
        total = asyncio.run(count_keys(args.redis_url, args.prefix))
        print(f"Anzahl Einträge mit Prefix '{args.prefix}*': {total}")
    else:
        total = asyncio.run(count_keys_where(args.redis_url, args.prefix, where))
        cond = " UND ".join([f"{k}={v!r}" for k, v in where])
        print(f"Anzahl Einträge mit Prefix '{args.prefix}*' und Bedingungen ({cond}): {total}")

if __name__ == "__main__":
    main()