#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Jaeger Trace Analyzer (ms version) — improved time window + robust empty handling
--------------------------------------------------------------------------------
- Holt Traces per conversation.id direkt aus Jaeger
- Unterstützt Lookback (Standard: 30 Tage) oder explizite Zeitfenster (--since/--until)
- Flatten der Spans in einen DataFrame
- Berechnet Turn-Metriken (Count, Avg-Dauer in Millisekunden)
- Extrahiert Patientendaten aus finalem LLM-Tool-Call (collect_patient_info)
  -> priorisiert Tool-Call mit is_complete == true
- Extrahiert Chatverlauf aus letztem LLM-Block (nur user/assistant)
- Hängt finale Assistant-Nachricht an:
  -> zuerst text_response (finaler Tool-Call), dann output-Tag des letzten LLM-Spans
- Liest eindeutigen Parameter (z.B. latency) aus Tags
- Optional: Dumps der Ergebnisse als JSON
"""

import argparse
import json
import sys
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests

# ------------------ Defaults ------------------ #
DEFAULT_JAEGER_URL  = "http://localhost:16686"
DEFAULT_SERVICE     = "voice_ai_latency_v2"
DEFAULT_CONV_TAG    = "conversation.id"
DEFAULT_TURN_OP     = "turn"
DEFAULT_LLM_OP      = "llm"
DEFAULT_INPUT_TAG   = "input"
DEFAULT_OUTPUT_TAG  = "output"
DEFAULT_FUNC_NAME   = "collect_patient_info"
DEFAULT_LATENCY_KEY = "latency"
DEFAULT_LOOKBACK_H  = 24 * 30  # 30 Tage
TZ                  = "Europe/Berlin"


# ------------------ Time helpers ------------------ #
def _to_utc_microseconds(ts: pd.Timestamp) -> int:
    """Convert pandas Timestamp (tz-aware or naive local) to epoch microseconds UTC."""
    if ts.tzinfo is None:
        ts = ts.tz_localize(TZ)
    ts_utc = ts.tz_convert("UTC")
    return int(ts_utc.timestamp() * 1_000_000)

def _parse_since_until(
    since: Optional[str],
    until: Optional[str],
    lookback_hours: Optional[int]
) -> Tuple[Optional[int], Optional[int]]:
    """
    Liefert (start_us, end_us) für Jaeger-Query.
    - Wenn since/until übergeben: nutze beide (falls nur since: until = now).
    - Sonst: nutze lookback_hours und end=now.
    Gibt None/None zurück, wenn nichts gesetzt (als Fallback).
    """
    if since or until:
        now = pd.Timestamp.utcnow().tz_localize("UTC")
        if until:
            until_ts = pd.to_datetime(until)
        else:
            until_ts = now
        if since:
            since_ts = pd.to_datetime(since)
        else:
            # falls nur until gegeben, nutze lookback oder 30 Tage
            lb_h = lookback_hours if lookback_hours is not None else DEFAULT_LOOKBACK_H
            since_ts = (pd.Timestamp(until_ts) - pd.Timedelta(hours=lb_h))
        start_us = _to_utc_microseconds(pd.Timestamp(since_ts))
        end_us   = _to_utc_microseconds(pd.Timestamp(until_ts))
        return start_us, end_us

    # since/until NICHT gesetzt -> Lookback benutzen
    if lookback_hours is None:
        lookback_hours = DEFAULT_LOOKBACK_H
    now_us = int(time.time() * 1_000_000)
    start_us = now_us - lookback_hours * 3600 * 1_000_000
    return start_us, now_us


# ------------------ Fetch ------------------ #
def fetch_traces_by_conv_id(conv_id: str,
                            base_url: str = DEFAULT_JAEGER_URL,
                            service: str = DEFAULT_SERVICE,
                            conv_tag_key: str = DEFAULT_CONV_TAG,
                            start_us: Optional[int] = None,
                            end_us: Optional[int] = None,
                            limit: int = 2000) -> Dict[str, Any]:
    """
    Holt Traces aus Jaeger. Zeitfenster:
    - Wenn start_us/end_us übergeben: verwendet diese.
    - Sonst: lässt weg (Jaeger hat dann ggf. restriktive Defaults).
    """
    tags = json.dumps({conv_tag_key: str(conv_id)})
    params = {"service": service, "tags": tags, "limit": str(limit)}
    # Viele Jaeger-Deployments erwarten start/end in Mikrosekunden (wie UI)
    if start_us is not None and end_us is not None:
        params["start"] = str(start_us)
        params["end"]   = str(end_us)

    resp = requests.get(f"{base_url}/api/traces", params=params)
    resp.raise_for_status()
    return resp.json()


# ------------------ Flatten ------------------ #
def spans_to_df(trace_json: Dict[str, Any]) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    for t in trace_json.get("data", []):
        for s in t.get("spans", []):
            tagdict = {}
            for tag in s.get("tags", []):
                # Defensive: manche Jaeger-Backends geben evtl. kein key/value-Format
                k = tag.get("key")
                v = tag.get("value")
                if k is not None:
                    tagdict[k] = v
            rows.append({
                "traceID":     s.get("traceID"),
                "spanID":      s.get("spanID"),
                "operation":   s.get("operationName"),
                "start_ns":    s.get("startTime"),
                "duration_ns": s.get("duration"),
                **tagdict
            })
    df = pd.DataFrame(rows)
    if not df.empty:
        # Zeilen ohne start/duration filtern
        df = df.dropna(subset=["start_ns", "duration_ns"])
        if not df.empty:
            df["start_ts"]    = pd.to_datetime(df["start_ns"], unit="ns", utc=True).dt.tz_convert(TZ)
            df["duration_ms"] = df["duration_ns"] / 1_000_000  # ms
    return df


# ------------------ Metrics ------------------ #
def turn_metrics(df: pd.DataFrame,
                 turn_operation: str = DEFAULT_TURN_OP,
                 interruption_tag: Optional[str] = None) -> Dict[str, Any]:
    if df.empty or "operation" not in df.columns:
        return {"turns": 0, "interruptions": 0, "avg_turn_ms": None}
    turn_df = df[df["operation"] == turn_operation].copy()
    turns = len(turn_df)
    avg_turn_ms = turn_df["duration_ms"].mean() if turns > 0 else None
    interruptions = 0
    if interruption_tag and interruption_tag in turn_df.columns:
        interruptions = (turn_df[interruption_tag].astype(str).str.lower() == "true").sum()
    return {
        "turns": turns,
        "interruptions": int(interruptions),
        "avg_turn_ms": float(avg_turn_ms) if avg_turn_ms is not None else None
    }

# --- Gesamt-Call-Dauer ------------------ #
def call_duration_ms(df: pd.DataFrame) -> Optional[float]:
    """
    Liefert die Gesamtdauer des Calls in Millisekunden.
    Bevorzugt den Root-Span mit operationName == 'conversation'.
    Fallback: (max(start+duration) - min(start)) über alle Spans.
    """
    if df is None or df.empty:
        return None
    # Bevorzugt: Root-Span "conversation" (enthält Gesamtdauer des Calls in ns)
    if "operation" in df.columns and "duration_ns" in df.columns:
        conv = df[df["operation"] == "conversation"]
        if not conv.empty:
            return float(conv.iloc[0]["duration_ns"] / 1_000_000.0)  # ns -> ms

        # Fallback über alle Spans
        if "start_ns" in df.columns and "duration_ns" in df.columns:
            start_min = df["start_ns"].min()
            end_max = (df["start_ns"] + df["duration_ns"]).max()
            return float((end_max - start_min) / 1_000_000.0)  # ns -> ms
    return None


# ------------------ Helpers ------------------ #
def robust_json_loads(s: Any) -> Any:
    """Verträgt bereits geparste Objekte, raw-Strings und doppelt encodete Strings."""
    if isinstance(s, (dict, list)):
        return s
    if s is None:
        return None
    if not isinstance(s, str):
        # Fallback: versuche JSON auf str(s)
        s = str(s)
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        # Versuch: doppelt encodiert -> zuerst ent-escapen
        return json.loads(json.loads(f'"{s}"'))


def _last_llm_row(df: pd.DataFrame, llm_operation: str) -> Optional[pd.Series]:
    if df.empty or "operation" not in df.columns:
        return None
    llm_df = df[df["operation"] == llm_operation]
    if llm_df.empty:
        return None
    return llm_df.sort_values("start_ns").iloc[-1]


# ------------------ LLM / Tool-Call Extraction ------------------ #
def get_last_llm_input(df: pd.DataFrame,
                       llm_operation: str = DEFAULT_LLM_OP,
                       input_tag_key: str = DEFAULT_INPUT_TAG) -> str:
    last_llm = _last_llm_row(df, llm_operation)
    if last_llm is None:
        raise ValueError("Kein LLM-Span gefunden.")
    if input_tag_key not in last_llm or pd.isna(last_llm[input_tag_key]):
        raise ValueError(f"Tag '{input_tag_key}' nicht im letzten LLM-Span vorhanden.")
    return str(last_llm[input_tag_key])


def get_last_llm_output(df: pd.DataFrame,
                        llm_operation: str = DEFAULT_LLM_OP,
                        output_tag_key: str = DEFAULT_OUTPUT_TAG) -> Optional[str]:
    last_llm = _last_llm_row(df, llm_operation)
    if last_llm is None:
        return None
    if output_tag_key in last_llm and pd.notna(last_llm[output_tag_key]):
        return str(last_llm[output_tag_key])
    return None


def extract_final_tool_call_args(input_json_str: str,
                                 function_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Sammelt alle passenden Tool-Calls; wählt den letzten mit is_complete==true,
    sonst den allerletzten. Gibt arguments als dict zurück.
    """
    messages = robust_json_loads(input_json_str) or []
    all_tools: List[Dict[str, Any]] = []
    for msg in messages:
        if isinstance(msg, dict) and msg.get("role") == "assistant" and "tool_calls" in msg:
            for tc in msg["tool_calls"]:
                fn = (tc or {}).get("function", {})
                if function_name is None or fn.get("name") == function_name:
                    args_raw = fn.get("arguments", "{}")
                    args = robust_json_loads(args_raw) or {}
                    all_tools.append({"fn": fn, "args": args})
    if not all_tools:
        raise ValueError("Kein passender Tool-Call im LLM-Input gefunden.")
    completed = [t for t in all_tools if str(t["args"].get("is_complete")).lower() == "true"]
    chosen = completed[-1] if completed else all_tools[-1]
    return {"name": chosen["fn"].get("name"), "arguments": chosen["args"]}


def get_patient_info_from_trace(df: pd.DataFrame,
                                llm_operation: str = DEFAULT_LLM_OP,
                                input_tag_key: str = DEFAULT_INPUT_TAG,
                                function_name: str = DEFAULT_FUNC_NAME) -> Dict[str, Any]:
    input_str = get_last_llm_input(df, llm_operation, input_tag_key)
    info = extract_final_tool_call_args(input_str, function_name)
    args = info["arguments"]
    return {
        "visit_reason":   args.get("visit_reason"),
        "first_name":     args.get("first_name"),
        "last_name":      args.get("last_name"),
        "phone":          args.get("phone"),
        "chosen_slot":    args.get("chosen_slot"),
        "slot_confirmed": args.get("slot_confirmed"),
        "is_complete":    args.get("is_complete"),
        "text_response":  args.get("text_response"),
    }


# ------------------ Chat Transcript ------------------ #
def extract_full_chat(input_json_str: str) -> List[Dict[str, str]]:
    """Nur Nachrichten mit role in {'user','assistant'} aus dem 'input'-JSON."""
    messages = robust_json_loads(input_json_str) or []
    transcript: List[Dict[str, str]] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        if role in {"user", "assistant"} and "content" in msg:
            transcript.append({"role": role, "content": str(msg["content"])})
    return transcript


def append_final_assistant_messages(transcript: List[Dict[str, str]],
                                    *candidates: Optional[str]) -> None:
    """Hängt (in Reihenfolge) nicht-leere, noch nicht vorhandene Assistant-Texte an."""
    def norm(s: str) -> str:
        return re.sub(r"\s+", " ", s or "").strip()
    existing = {norm(m["content"]) for m in transcript if m.get("role") == "assistant"}
    for c in candidates:
        if not c:
            continue
        nc = norm(c)
        if nc and nc not in existing:
            transcript.append({"role": "assistant", "content": c})
            existing.add(nc)


# ------------------ Unique Param ------------------ #
def extract_unique_param(df: pd.DataFrame, key: str) -> Optional[str]:
    if df.empty or key not in df.columns:
        return None
    vals = df[key].dropna().astype(str).unique()
    return vals[0] if len(vals) > 0 else None


# ------------------ CLI ------------------ #
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Jaeger conversation trace analyzer (ms)")
    p.add_argument("--conv-id", required=True, help="conversation.id Wert")
    p.add_argument("--jaeger-url", default=DEFAULT_JAEGER_URL, help="Jaeger Query Base URL")
    p.add_argument("--service", default=DEFAULT_SERVICE, help="Service-Name")
    p.add_argument("--conv-tag", default=DEFAULT_CONV_TAG, help="Tag-Key für conversation.id")
    p.add_argument("--turn-op", default=DEFAULT_TURN_OP, help="operationName für Turn-Spans")
    p.add_argument("--llm-op", default=DEFAULT_LLM_OP, help="operationName für LLM-Spans")
    p.add_argument("--input-tag", default=DEFAULT_INPUT_TAG, help="Tag-Key mit Chatverlauf")
    p.add_argument("--output-tag", default=DEFAULT_OUTPUT_TAG, help="Tag-Key mit finalem Output")
    p.add_argument("--func-name", default=DEFAULT_FUNC_NAME, help="Function-Name im Tool-Call")
    p.add_argument("--interrupt-tag", default=None, help="Optionaler Tag für Unterbrechungen")
    p.add_argument("--latency-key", default=DEFAULT_LATENCY_KEY, help="Eindeutiger Parameter (z.B. latency)")

    # Zeitfenster / Lookback
    p.add_argument("--lookback-hours", type=int, default=DEFAULT_LOOKBACK_H,
                   help="Lookback in Stunden (Standard: 30 Tage)")
    p.add_argument("--since", type=str, default=None,
                   help="Startzeit (z.B. '2025-10-01 00:00', lokal Europe/Berlin, ISO-Format ok)")
    p.add_argument("--until", type=str, default=None,
                   help="Endzeit (z.B. '2025-10-08 23:59', lokal Europe/Berlin, ISO-Format ok)")

    # Limits
    p.add_argument("--limit", type=int, default=2000, help="Max. Anzahl Traces (Standard: 2000)")

    # Dumps
    p.add_argument("--dump-chat", default=None, help="Pfad: Chatverlauf JSON speichern")
    p.add_argument("--dump-patient", default=None, help="Pfad: Patientendaten JSON speichern")
    p.add_argument("--dump-metrics", default=None, help="Pfad: Metriken JSON speichern")
    return p.parse_args()


# ------------------ Main ------------------ #
def main():
    args = parse_args()

    # Zeitfenster vorbereiten
    try:
        start_us, end_us = _parse_since_until(args.since, args.until, args.lookback_hours)
    except Exception as e:
        print(f"[ERROR] Zeitfenster ungültig: {e}", file=sys.stderr)
        sys.exit(2)

    # Fetch
    try:
        raw = fetch_traces_by_conv_id(
            conv_id=args.conv_id,
            base_url=args.jaeger_url,
            service=args.service,
            conv_tag_key=args.conv_tag,
            start_us=start_us,
            end_us=end_us,
            limit=args.limit
        )
    except Exception as e:
        print(f"[ERROR] Fetch failed: {e}", file=sys.stderr)
        sys.exit(1)

    df = spans_to_df(raw)

    if df.empty:
        # Freundliche, klare Ausgabe statt späterem KeyError
        print("[WARN] Keine Spans für diese Parameter gefunden.")
        print("\n=== Turn-Metriken ===")
        print(f"Conversation ID : {args.conv_id}")
        print(f"Turns           : 0")
        print(f"Unterbrechungen : 0")
        print("Ø Turn-Dauer ms : n/a")
        print(f"\n{args.latency_key.capitalize():15}: None")
        sys.exit(0)

    # Metrics
    metrics = turn_metrics(
        df,
        turn_operation=args.turn_op,
        interruption_tag=args.interrupt_tag
    )

    latency_val = extract_unique_param(df, args.latency_key)

    # Chat + Patient + Finale
    patient_info: Dict[str, Any] = {}
    chat_transcript: List[Dict[str, str]] = []
    final_output: Optional[str] = None

    try:
        input_str = get_last_llm_input(df, args.llm_op, args.input_tag)
        chat_transcript = extract_full_chat(input_str)
        patient_info = get_patient_info_from_trace(
            df,
            llm_operation=args.llm_op,
            input_tag_key=args.input_tag,
            function_name=args.func_name
        )
        final_output = get_last_llm_output(df, args.llm_op, args.output_tag)
    except Exception as e:
        print(f"[WARN] Chat/Patient extraction failed: {e}", file=sys.stderr)

    # Finale Assistant-Nachricht(en) anhängen:
    # 1) text_response des finalen Tool-Calls  2) output-Tag
    append_final_assistant_messages(
        chat_transcript,
        patient_info.get("text_response") if patient_info else None,
        final_output
    )

    # ----- Ausgabe ----- #
    print("\n=== Turn-Metriken ===")
    print(f"Conversation ID : {args.conv_id}")
    print(f"Turns           : {metrics['turns']}")
    print(f"Unterbrechungen : {metrics['interruptions']}")
    print(f"Gesamt-Call-Dauer ms : {call_duration_ms(df):.2f}")
    if metrics['avg_turn_ms'] is not None:
        print(f"Ø Turn-Dauer ms : {metrics['avg_turn_ms']:.2f}")
    else:
        print("Ø Turn-Dauer ms : n/a")

    print(f"\n{args.latency_key.capitalize():15}: {latency_val}")

    if patient_info:
        print("\n=== Patientendaten (finaler Tool-Call) ===")
        for k, v in patient_info.items():
            print(f"{k:14}: {v}")

    if chat_transcript:
        print("\n=== Chatverlauf ===")
        for msg in chat_transcript:
            print(f"{msg['role']:>9}: {msg['content']}")

    # Dumps
    if args.dump_chat and chat_transcript:
        with open(args.dump_chat, "w", encoding="utf-8") as f:
            json.dump(chat_transcript, f, ensure_ascii=False, indent=2)
        print(f"\n[INFO] Chatverlauf gespeichert in {args.dump_chat}")

    if args.dump_patient and patient_info:
        with open(args.dump_patient, "w", encoding="utf-8") as f:
            json.dump(patient_info, f, ensure_ascii=False, indent=2)
        print(f"[INFO] Patientendaten gespeichert in {args.dump_patient}")

    if args.dump_metrics:
        to_dump = {
            "conversation_id": args.conv_id,
            **metrics,
            args.latency_key: latency_val
        }
        with open(args.dump_metrics, "w", encoding="utf-8") as f:
            json.dump(to_dump, f, ensure_ascii=False, indent=2)
        print(f"[INFO] Metriken gespeichert in {args.dump_metrics}")


if __name__ == "__main__":
    main()
