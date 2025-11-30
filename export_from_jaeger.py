# # Jaeger → Polars Exporter (60 Tage, Service: voice_ai_latency_v2_pilot_1)
# - Lädt Traces in Tages-Chunks
# - Speichert jede Trace als JSON (eine Datei pro TraceID)
# - Erstellt Polars-DataFrames (spans + traces)
# - Exportiert als Parquet & Arrow IPC (Polars-kompatibel)

# %pip install --quiet polars pyarrow requests tqdm python-dateutil

import os
import json
import math
import time
import pathlib
import datetime as dt
from typing import Dict, Any, List, Tuple, Optional

import requests
import polars as pl
from dateutil.relativedelta import relativedelta
from tqdm import tqdm

# ------------ Konfiguration ------------
JAEGER_BASE_URL   = os.environ.get("JAEGER_BASE_URL", "http://localhost:16686")  # <- anpassen!
SERVICE_NAME      = "voice_ai_latency_v2_pilot_1"                                 # <- wie gewünscht
DAYS_BACK         = 90                                                            # letzte 60 Tage
CHUNK_DAYS        = 1                                                             # in 1-Tages-Chunks ziehen
REQUEST_LIMIT     = 2000                                                          # Jaeger 'limit' pro Request
TIMEZONE          = dt.timezone.utc                                               # Input-Zeit -> UTC für Jaeger

# Auth (optional). Beispiel: os.environ["JAEGER_AUTH_TOKEN"]="eyJ..."
JAEGER_AUTH_TOKEN = os.environ.get("JAEGER_AUTH_TOKEN", "").strip()

# Ausgabeordner (timestamped)
RUN_STAMP  = dt.datetime.now(tz=TIMEZONE).strftime("%Y%m%d_%H%M%S")
BASE_OUT   = pathlib.Path(f"./jaeger_exports/{SERVICE_NAME}/{RUN_STAMP}").resolve()
JSON_DIR   = BASE_OUT / "json_traces"
EXPORT_DIR = BASE_OUT / "exports"

JSON_DIR.mkdir(parents=True, exist_ok=True)
EXPORT_DIR.mkdir(parents=True, exist_ok=True)

print("Base URL       :", JAEGER_BASE_URL)
print("Service        :", SERVICE_NAME)
print("Zeitraum       :", f"letzte {DAYS_BACK} Tage")
print("Chunkgröße     :", f"{CHUNK_DAYS} Tag(e)")
print("Limit/Request  :", REQUEST_LIMIT)
print("Output-Ordner  :", str(BASE_OUT))
print("Auth aktiv?    :", bool(JAEGER_AUTH_TOKEN))

def to_unix_ns(dt_obj: dt.datetime) -> int:
    """Konvertiert ein aware datetime in UNIX Nanosekunden."""
    if dt_obj.tzinfo is None:
        raise ValueError("to_unix_ns erwartet eine timezone-aware datetime.")
    return int(dt_obj.timestamp() * 1_000_000_000)

def daterange_chunks(end_incl: dt.datetime, days_back: int, chunk_days: int) -> List[Tuple[dt.datetime, dt.datetime]]:
    """
    Erzeuge [start, end] Chunks (geschlossenes Intervall) in UTC.
    end_incl: Endzeitpunkt (inklusive), i. d. R. jetzt
    """
    end_incl = end_incl.astimezone(TIMEZONE)
    start_all = (end_incl - relativedelta(days=days_back))
    chunks = []
    cur_start = start_all
    while cur_start < end_incl:
        cur_end = min(cur_start + relativedelta(days=chunk_days), end_incl)
        chunks.append((cur_start, cur_end))
        cur_start = cur_end
    return chunks


# %% 
session = requests.Session()
headers = {}
if JAEGER_AUTH_TOKEN:
    headers["Authorization"] = f"Bearer {JAEGER_AUTH_TOKEN}"

def _to_epoch_us(dt_obj: dt.datetime) -> int:
    return int(dt_obj.timestamp() * 1_000_000)

def _to_epoch_ns(dt_obj: dt.datetime) -> int:
    return int(dt_obj.timestamp() * 1_000_000_000)

def _to_epoch_ms(dt_obj: dt.datetime) -> int:
    return int(dt_obj.timestamp() * 1_000)

def _jaeger_get(path: str, params: dict, timeout: int = 60):
    url = f"{JAEGER_BASE_URL.rstrip('/')}{path}"
    resp = session.get(url, params=params, headers=headers, timeout=timeout)
    return resp

def list_services() -> list:
    """Hilfsfunktion: Liste der Services von Jaeger holen (zum Debuggen)."""
    try:
        resp = _jaeger_get("/api/services", {})
        if resp.status_code == 200:
            js = resp.json()
            return js.get("data", []) or []
    except Exception:
        pass
    return []

def fetch_traces_chunk_resilient(
    service: str,
    start_dt: dt.datetime,
    end_dt: dt.datetime,
    limit: int = 2000,
    retries: int = 2,
    timeout: int = 60,
) -> tuple[list, str]:
    """
    Robust: versucht 'start'/'end' in Mikrosekunden, dann Nanosekunden, dann Millisekunden.
    Gibt (traces, unit_label) zurück, wobei unit_label in {"us","ns","ms"} liegt.
    """
    # Reihenfolge der Versuche: µs → ns → ms (häufig ist µs korrekt)
    attempts = [
        ("us", _to_epoch_us),
        ("ns", _to_epoch_ns),
        ("ms", _to_epoch_ms),
    ]
    last_err = None
    for unit_label, fn in attempts:
        params = {
            "service": service,
            "start": str(fn(start_dt)),
            "end":   str(fn(end_dt)),
            "limit": str(limit),
        }
        for _ in range(retries):
            try:
                resp = _jaeger_get("/api/traces", params, timeout=timeout)
                if resp.status_code == 200:
                    payload = resp.json()
                    data = payload.get("data", []) or []
                    # Wir akzeptieren 200 + leere Liste (kann legit sein),
                    # aber wir geben trotzdem die genutzte Einheit zurück.
                    return data, unit_label
                else:
                    last_err = RuntimeError(f"[{unit_label}] HTTP {resp.status_code}: {resp.text[:200]}")
            except Exception as e:
                last_err = e
            time.sleep(0.5)
    # Falls alles scheitert, Exception weiterreichen
    raise last_err if last_err else RuntimeError("Fetch fehlgeschlagen (alle Einheiten versucht).")

# Sanity-Check: Service existiert?
_services = list_services()
print("Services (Auszug):", _services[:10])
if SERVICE_NAME not in _services:
    print(f"⚠️ Hinweis: Service '{SERVICE_NAME}' wurde nicht in /api/services gefunden.")
    print("   • Prüfe Schreibweise / genaue Service-Bezeichnung in Jaeger")
    print("   • Prüfe Auth/Berechtigungen (falls vorhanden)")
    print("   • Prüfe Retention (evtl. keine Traces in den letzten 60 Tagen)")
else:
    print(f"✅ Service '{SERVICE_NAME}' ist vorhanden.")

# Zeitfenster (Chunks) bauen
now_utc = dt.datetime.now(tz=TIMEZONE)
chunks = daterange_chunks(now_utc, DAYS_BACK, CHUNK_DAYS)
print(f"Erzeuge {len(chunks)} Zeit-Chunks von {chunks[0][0]} bis {chunks[-1][1]} (UTC).")


# %%
all_traces: Dict[str, Dict[str, Any]] = {}  # traceID -> trace-json
unit_usage_counts = {"us": 0, "ns": 0, "ms": 0}

for start_dt, end_dt in tqdm(chunks, desc="Lade Jaeger-Chunks"):
    traces, unit_label = fetch_traces_chunk_resilient(
        service=SERVICE_NAME,
        start_dt=start_dt,
        end_dt=end_dt,
        limit=REQUEST_LIMIT,
    )
    unit_usage_counts[unit_label] += 1
    # Deduplicate by traceID (bei Überschneidungen/Limit)
    for tr in traces:
        trace_id = tr.get("traceID") or tr.get("traceId")
        if trace_id:
            all_traces[trace_id] = tr

print(f"Gesamt geladene Traces: {len(all_traces)}")
print("Benutzte Zeit-Einheiten für Requests:", unit_usage_counts)

# Zusätzliche Hinweise, falls 0 Traces:
if len(all_traces) == 0:
    print("\n🚫 Es wurden 0 Traces gefunden.")
    print("Mögliche Ursachen & Checks:")
    print("  1) Retention: Sind überhaupt Traces der letzten 60 Tage vorhanden?")
    print("  2) Service-Name: Exakt wie in Jaeger? (siehe Auszug aus /api/services oben)")
    print("  3) Auth: Token / Rechte korrekt gesetzt?")
    print("  4) Base-URL: Zeigt JAEGER_BASE_URL auf jaeger-query (nicht collector)?")
    print("  5) Zeitfenster: TIMEZONE/UTC korrekt? (wir nutzen UTC)")


def save_trace_json(trace: Dict[str, Any], out_dir: pathlib.Path) -> pathlib.Path:
    trace_id = trace.get("traceID") or trace.get("traceId") or f"no_id_{int(time.time())}"
    path = out_dir / f"{trace_id}.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(trace, f, ensure_ascii=False, indent=2)
    return path

saved_paths = []
for tr in tqdm(all_traces.values(), desc="Speichere JSON pro Trace"):
    p = save_trace_json(tr, JSON_DIR)
    saved_paths.append(p)

print(f"Gespeicherte JSON-Dateien: {len(saved_paths)}")
print("Beispiel:", saved_paths[0] if saved_paths else "—")


# Polars DataFrames bauen

# %%
# RAW: jedes Trace exakt als Original-JSON im DataFrame festhalten (verlustfrei)
raw_rows = []
for tr in all_traces.values():
    trace_id = tr.get("traceID") or tr.get("traceId")
    # json.dumps ohne Pretty-Print -> kompakte, deterministische Darstellung
    raw_rows.append({
        "trace_id": trace_id,
        "trace_json": json.dumps(tr, ensure_ascii=False, separators=(",", ":"))
    })

df_traces_raw = pl.DataFrame(raw_rows)
print(df_traces_raw.shape, "→ df_traces_raw")
print(df_traces_raw.head(2))

# Beispiel: 1:1 zurück zu Python-Objekt
example_json = df_traces_raw["trace_json"].to_list()[0] if df_traces_raw.height > 0 else None
if example_json:
    example_obj = json.loads(example_json)
    print("Roundtrip-Check für eine Zeile OK:", isinstance(example_obj, dict))

# %%
traces_raw_parquet = EXPORT_DIR / "traces_raw.parquet"
traces_raw_ipc     = EXPORT_DIR / "traces_raw.arrow"

df_traces_raw.write_parquet(traces_raw_parquet)
df_traces_raw.write_ipc(traces_raw_ipc)

print("RAW-Exports geschrieben:")
print(" -", traces_raw_parquet)
print(" -", traces_raw_ipc)



df_traces_raw_re = pl.read_parquet(traces_raw_parquet)
print("RAW re-import shape:", df_traces_raw_re.shape)

# Roundtrip-Test: gleicher Inhalt zurück zu dict
if df_traces_raw_re.height > 0:
    raw_str = df_traces_raw_re["trace_json"].to_list()[0]
    obj = json.loads(raw_str)
    print("Beispiel-Trace hat Keys:", list(obj.keys())[:5], "…")