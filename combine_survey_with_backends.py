#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
combine_survey_with_backends.py (robust + manuelle CSV-Overrides)
-----------------------------------------------------------------
- CSV-Delimiter wird automatisch aus den ersten Bytes erkannt (Fallback auf ';').
- Optional: --sep, --quotechar, --encoding zum Überschreiben.
- Entfernt BOM, Anführungszeichen und trimmt Whitespace aus Spaltennamen.
- Nutzt CHECK_CODE als Schlüssel und ruft:
    - Redis (via show_call.py)  -> Felder mit 'redis_' (redundant) präfixt
    - Jaeger (via jaeger_conv_stats.py)
- Speichert kombinierte CSV.

Beispiel:
  python combine_survey_with_backends.py \
      --input data_project_1069195_2025_09_26.csv \
      --output combined.csv
"""

import argparse
import asyncio
import sys
from typing import Dict, Any, Optional, Tuple

import pandas as pd
import os


# ---- Import der bestehenden Hilfsfunktionen aus deinen Skripten ----
try:
    from show_call import fetch_call as redis_fetch_call  # async
except Exception as e:
    print(f"[FATAL] Konnte show_call.py nicht importieren: {e}", file=sys.stderr)
    sys.exit(2)

try:
    from jaeger_conv_stats import (
        fetch_traces_by_conv_id,
        spans_to_df,
        turn_metrics,
        extract_unique_param,
        get_patient_info_from_trace,
        get_last_llm_output,
        get_last_llm_input,
        _parse_since_until,
        DEFAULT_LLM_OP,
        DEFAULT_INPUT_TAG,
        DEFAULT_OUTPUT_TAG,
        call_duration_ms,
    )
except Exception as e:
    print(f"[FATAL] Konnte jaeger_conv_stats.py nicht importieren: {e}", file=sys.stderr)
    sys.exit(2)


def _clean_colname(col: str) -> str:
    if not isinstance(col, str):
        return col
    # BOM entfernen + trimmen
    col = col.replace("\ufeff", "").strip()
    # umschließende Quotes entfernen
    if len(col) >= 2 and ((col[0] == '"' and col[-1] == '"') or (col[0] == "'" and col[-1] == "'")):
        col = col[1:-1]
    return col.strip()


def _strip_quotes_from_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [_clean_colname(c) for c in df.columns]
    return df


def _detect_csv_params(path: str) -> Tuple[str, str]:
    """
    Erkenne Delimiter aus den ersten Bytes der Datei.
    Rückgabe: (sep, quotechar)
    """
    import csv
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            sample = f.read(8192)
    except FileNotFoundError:
        raise
    if not sample:
        # Leere Datei – Default auf ';'
        return ";", '"'
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=[",", ";", "\t", "|"])
        sep = dialect.delimiter
    except Exception:
        sep = ";"
    quotechar = '"'
    return sep, quotechar


def load_csv_smart(path: str, sep_opt: Optional[str] = None, quote_opt: Optional[str] = None,
                   encoding_opt: str = "utf-8") -> pd.DataFrame:
    # Manuelle Overrides oder Auto-Detection
    if sep_opt is None or quote_opt is None:
        det_sep, det_quote = _detect_csv_params(path)
        sep = sep_opt or det_sep
        quotechar = quote_opt or det_quote
    else:
        sep, quotechar = sep_opt, quote_opt

    # Hauptversuch
    try:
        df = pd.read_csv(path, sep=sep, quotechar=quotechar, encoding=encoding_opt, engine="python")
    except UnicodeDecodeError:
        # Fallback Encoding
        df = pd.read_csv(path, sep=sep, quotechar=quotechar, encoding="latin1", engine="python")
    df = _strip_quotes_from_columns(df)

    # Falls „alles in einer Spalte“ → Fallback mit ';'
    if len(df.columns) == 1:
        try:
            df = pd.read_csv(path, sep=";", quotechar=quotechar, encoding=encoding_opt, engine="python")
        except UnicodeDecodeError:
            df = pd.read_csv(path, sep=";", quotechar=quotechar, encoding="latin1", engine="python")
        df = _strip_quotes_from_columns(df)

    return df


def prefix_keys(data: Dict[str, Any], prefix: str) -> Dict[str, Any]:
    return {f"{prefix}{k}": v for k, v in data.items()}


async def fetch_redis_blocking(redis_url: str, prefix: str, call_id: str) -> Dict[str, Any]:
    try:
        _key, data = await redis_fetch_call(redis_url, prefix, call_id)
        return data or {}
    except Exception as e:
        print(f"[WARN] Redis-Fetch für call_id={call_id} fehlgeschlagen: {e}", file=sys.stderr)
        return {}


def fetch_jaeger(conv_id: str, jaeger_url: str, service: str, lookback_hours: Optional[int]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    try:
        start_us, end_us = _parse_since_until(since=None, until=None, lookback_hours=lookback_hours)
        raw = fetch_traces_by_conv_id(
            conv_id=str(conv_id),
            base_url=jaeger_url,
            service=service,
            start_us=start_us,
            end_us=end_us,
            limit=2000,
        )
        df = spans_to_df(raw)
        if df is None or df.empty:
            result["jaeger_found"] = False
            return result

        metrics = turn_metrics(df)
        result["jaeger_found"] = True
        result["jaeger_turns"] = metrics.get("turns")
        result["jaeger_interruptions"] = metrics.get("interruptions")
        result["jaeger_avg_turn_ms"] = metrics.get("avg_turn_ms")

        latency_val = extract_unique_param(df, "latency")
        result["jaeger_latency"] = latency_val
                # Gesamtdauer (aus Root-Span "conversation" oder Fallback)
        total_ms = call_duration_ms(df)
        if total_ms is not None:
            result["jaeger_call_duration_s"] = round(float(total_ms), 3)



        try:
            _ = get_last_llm_input(df, llm_operation=DEFAULT_LLM_OP, input_tag_key=DEFAULT_INPUT_TAG)
            patient_info = get_patient_info_from_trace(
                df,
                llm_operation=DEFAULT_LLM_OP,
                input_tag_key=DEFAULT_INPUT_TAG,
            )
            for k, v in patient_info.items():
                result[f"jaeger_{k}"] = v
        except Exception as e:
            print(f"[INFO] Keine Patient/Toolcall-Infos in Jaeger für conv-id={conv_id}: {e}", file=sys.stderr)

        try:
            final_output = get_last_llm_output(df, llm_operation=DEFAULT_LLM_OP, output_tag_key=DEFAULT_OUTPUT_TAG)
            if final_output:
                result["jaeger_final_output"] = final_output
        except Exception:
            pass

        return result
    except Exception as e:
        print(f"[WARN] Jaeger-Fetch für conv-id={conv_id} fehlgeschlagen: {e}", file=sys.stderr)
        result["jaeger_found"] = False
        return result


def main():
    ap = argparse.ArgumentParser(description="Merge Umfrage-CSV mit Redis & Jaeger Daten (robust)")
    ap.add_argument("--input", required=True, help="Pfad zur Umfrage-CSV (muss Spalte CHECK_CODE enthalten)")
    ap.add_argument("--output", required=True, help="Pfad für die kombinierte CSV")

    # Jaeger
    ap.add_argument("--jaeger-url", default="http://localhost:16686", help="Jaeger Query URL")
    ap.add_argument("--service", default="voice_ai_latency_v2_pilot_1",
                    help="Jaeger Service-Name (Standard: voice_ai_latency_v2_pilot_1)")
    ap.add_argument("--lookback-hours", type=int, default=24*60, help="Lookback Fenster in Stunden (Default 30 Tage)")

    # Redis
    ap.add_argument("--redis-url", default="redis://localhost:6379/0", help="Redis URL")
    ap.add_argument("--redis-prefix", default="voiceai:call:", help="Redis Key-Prefix")

    # CSV Optionen
    ap.add_argument("--check-code-column", default="CHECK_CODE",
                    help="Spaltenname in der CSV für den gemeinsamen Schlüssel (Default: CHECK_CODE)")
    ap.add_argument("--sep", default=None, help="CSV Trennzeichen überschreiben (z.B. ';' oder ','). Optional.")
    ap.add_argument("--quotechar", default=None, help="CSV Quotechar überschreiben (z.B. '\"'). Optional.")
    ap.add_argument("--encoding", default="utf-8", help="CSV Encoding (Default: utf-8). Optional.")

    ap.add_argument("--output-jaeger", default=None, help="Pfad für Jaeger-only CSV (optional)")
    ap.add_argument("--output-redis", default=None, help="Pfad für Redis-only CSV (optional)")


    args = ap.parse_args()

    # CSV laden (smart, mit optionalen Overrides)
    df = load_csv_smart(args.input, sep_opt=args.sep, quote_opt=args.quotechar, encoding_opt=args.encoding)

    # Spaltennamen anzeigen (Debug)
    print(f"[INFO] Erkannte Spalten: {list(df.columns)}")

    # CHECK_CODE-Spalte sicher finden (case-insensitive)
    possible_cols = {str(c).upper(): str(c) for c in df.columns}
    target_key_upper = args.check_code_column.upper()
    if target_key_upper not in possible_cols:
        # Zusätzliche bereinigte Map prüfen
        fixed_map = {_clean_colname(str(k)).upper(): str(k) for k in df.columns}
        if target_key_upper in fixed_map:
            check_col = fixed_map[target_key_upper]
        else:
            print(f"[FATAL] Spalte '{args.check_code_column}' nicht in CSV gefunden. "
                  f"Spalten: {list(df.columns)}", file=sys.stderr)
            sys.exit(1)
    else:
        check_col = possible_cols[target_key_upper]

    # Eindeutige Keys
    codes = pd.Series(df[check_col]).dropna().astype(str).unique().tolist()
    print(f"[INFO] {len(codes)} eindeutige {check_col}-Werte gefunden. Starte Abfragen...")

    # Caches
    redis_cache: Dict[str, Dict[str, Any]] = {}
    jaeger_cache: Dict[str, Dict[str, Any]] = {}

    # Redis
    for code in codes:
        data = asyncio.run(fetch_redis_blocking(args.redis_url, args.redis_prefix, code))
        redis_cache[code] = prefix_keys(data, "redis_")

    # Jaeger
    for code in codes:
        jaeger_cache[code] = fetch_jaeger(code, args.jaeger_url, args.service, args.lookback_hours)

    # Merge
    merged_rows = []
    for _, row in df.iterrows():
        raw_val = row.get(check_col)
        code = str(raw_val) if pd.notna(raw_val) else None

        extra: Dict[str, Any] = {}
        if code:
            extra.update(redis_cache.get(code, {}))   # redundant -> 'redis_*'
            extra.update(jaeger_cache.get(code, {}))  # jaeger_*
            # Flags
            extra["redis_found"] = bool(redis_cache.get(code))
            if "jaeger_found" not in extra:
                extra["jaeger_found"] = False

        merged_rows.append({**row.to_dict(), **extra})

    out_df = pd.DataFrame(merged_rows)
    out_df.to_csv(args.output, index=False)
    print(f"[OK] Kombinierte CSV gespeichert: {args.output}")

    # --- Teil-Exporte: nur Jaeger / nur Redis ---
    root, ext = os.path.splitext(args.output)
    jaeger_path = args.output_jaeger or f"{root}_jaeger{ext or '.csv'}"
    redis_path  = args.output_redis  or f"{root}_redis{ext or '.csv'}"

    # Spaltenlisten zusammenstellen (Schlüsselspalte + spezifische Präfixe + Flags)
    base_cols = [check_col]

    jaeger_cols = []
    if "jaeger_found" in out_df.columns:
        jaeger_cols.append("jaeger_found")
    jaeger_cols += [c for c in out_df.columns if str(c).startswith("jaeger_")]

    redis_cols = []
    if "redis_found" in out_df.columns:
        redis_cols.append("redis_found")
    redis_cols += [c for c in out_df.columns if str(c).startswith("redis_")]

    # Reihenfolge: zuerst Schlüsselspalte, dann die spezifischen Spalten (Duplikate vermeiden)
    def unique(seq):
        seen = set()
        return [x for x in seq if not (x in seen or seen.add(x))]

    jaeger_cols = unique(base_cols + jaeger_cols)
    redis_cols  = unique(base_cols + redis_cols)

    # Leere Spaltenlisten verhindern (falls z.B. nichts gefunden wurde)
    if len(jaeger_cols) > 1:
        out_df.loc[:, jaeger_cols].to_csv(jaeger_path, index=False)
        print(f"[OK] Jaeger-only CSV gespeichert: {jaeger_path}")
    else:
        print("[HINWEIS] Keine Jaeger-Spalten zum Export gefunden.")

    if len(redis_cols) > 1:
        out_df.loc[:, redis_cols].to_csv(redis_path, index=False)
        print(f"[OK] Redis-only CSV gespeichert: {redis_path}")
    else:
        print("[HINWEIS] Keine Redis-Spalten zum Export gefunden.")

    print(f"[HINWEIS] Redis-Felder sind redundant und mit 'redis_' geprefixt. Jaeger-Service: {args.service}")


if __name__ == "__main__":
    main()
