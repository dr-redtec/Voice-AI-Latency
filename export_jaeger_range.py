#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Exportiere Jaeger-Daten für einen numerischen ID-Bereich (z.B. 200-500)
ohne Merge mit einer CSV. Nicht gefundene IDs werden still übersprungen.

Beispiel:
  python export_jaeger_range.py \
    --range 200-500 \
    --output jaeger_200_500.csv \
    --jaeger-url http://localhost:16686 \
    --service voice_ai_latency_v2_pilot_1 \
    --lookback-hours 720
"""

import argparse
import sys
from typing import Dict, Any, List, Tuple, Optional
import pandas as pd

# ---- Import der bestehenden Jaeger-Helfer wie im Merge-Skript ----
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


def parse_range(spec: str) -> Tuple[int, int]:
    spec = spec.strip().replace(" ", "")
    if "-" not in spec:
        raise ValueError("Range muss das Format START-END haben, z.B. 200-800")
    a, b = spec.split("-", 1)
    start, end = int(a), int(b)
    if end < start:
        start, end = end, start
    return start, end


def fetch_jaeger(conv_id: str, jaeger_url: str, service: str, lookback_hours: Optional[int]) -> Dict[str, Any]:
    """
    Holt Jaeger-Daten und liefert jaeger_* Felder + jaeger_found Flag.
    """
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

        total_ms = call_duration_ms(df)
        if total_ms is not None:
            # call_duration_ms -> wir speichern in Sekunden mit 3 Nachkommastellen
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
        except Exception:
            pass

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
    ap = argparse.ArgumentParser(description="Exportiere Jaeger-Daten für einen ID-Bereich (ohne Merge).")
    ap.add_argument("--range", required=True, help="Numerischer Bereich, z.B. 200-500 (inklusive).")
    ap.add_argument("--output", required=True, help="Ziel-CSV.")
    ap.add_argument("--id-column", default="CHECK_CODE",
                    help="Spaltenname für die ID in der Ausgabe (Default: CHECK_CODE).")

    # Jaeger-Parameter
    ap.add_argument("--jaeger-url", default="http://localhost:16686", help="Jaeger Query URL")
    ap.add_argument("--service", default="voice_ai_latency_v2_pilot_1",
                    help="Jaeger Service-Name (Default: voice_ai_latency_v2_pilot_1)")
    ap.add_argument("--lookback-hours", type=int, default=24*60, help="Lookback-Fenster in Stunden (Default: 30 Tage)")

    # Optionales Verhalten
    ap.add_argument("--include-missing", action="store_true",
                    help="Wenn gesetzt, schreibe auch IDs ohne Jaeger-Daten (jaeger_found=False) in die CSV. "
                         "Standard: fehlende IDs werden übersprungen.")

    args = ap.parse_args()

    start, end = parse_range(args.range)
    ids = list(range(start, end + 1))
    print(f"[INFO] Frage Jaeger für IDs {start}..{end} ab (insgesamt {len(ids)})")

    rows: List[Dict[str, Any]] = []
    for n in ids:
        conv_id = str(n)
        data = fetch_jaeger(conv_id, args.jaeger_url, args.service, args.lookback_hours)
        # FIX: argparse macht aus --include-missing -> args.include_missing
        if data.get("jaeger_found") or args.include_missing:
            row = {args.id_column: conv_id, **data}
            rows.append(row)

    if not rows:
        print("[HINWEIS] Keine Einträge zum Export (vermutlich nichts im Range gefunden).")
        # Trotzdem leere CSV mit Kopf schreiben, damit der Schritt reproduzierbar bleibt
        pd.DataFrame(columns=[args.id_column, "jaeger_found"]).to_csv(args.output, index=False)
        print(f"[OK] CSV (leer) geschrieben: {args.output}")
        return

    # Spaltenreihenfolge: ID, jaeger_found, alle jaeger_* Felder
    df = pd.DataFrame(rows)
    col_id = [args.id_column] if args.id_column in df.columns else []
    col_found = ["jaeger_found"] if "jaeger_found" in df.columns else []
    jaeger_cols = [c for c in df.columns if c.startswith("jaeger_")]
    other_cols = [c for c in df.columns if c not in set(col_id + col_found + jaeger_cols)]
    ordered = col_id + col_found + jaeger_cols + other_cols
    df = df.loc[:, ordered]

    df.to_csv(args.output, index=False)
    print(f"[OK] Jaeger-Range-CSV geschrieben: {args.output}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[ABBRUCH] Vom Nutzer beendet.", file=sys.stderr)
        sys.exit(130)
