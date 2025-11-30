#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
print_combined_tables.py
------------------------
Liest combined.csv und zeigt die Daten übersichtlich in DREI Tabellen:
  1) Umfrage   (CHECK_CODE, *_Exp, *_Per)
  2) Jaeger    (jaeger_*)
  3) Redis     (redis_* - redundant)

Features:
- Auto-Delimiter für CSV (Fallback ';'), Quotechar='"', Encoding-Fallback latin1
- Spaltennamen-Bereinigung (BOM, Quotes)
- Fehlende Spalten werden leer ergänzt
- Lange Textfelder (response/chat/history/output) werden zeilenweise UMGEBROCHEN und
  auf eine maximale Anzahl Zeilen pro Zelle begrenzt (konfigurierbar)

Beispiele:
  python print_combined_tables.py --input combined.csv
  python print_combined_tables.py --input combined.csv --width 100 --max-lines 6
  python print_combined_tables.py --input combined.csv --head 25
"""

import argparse
import sys
import textwrap
from typing import List, Tuple, Optional, Iterable

import pandas as pd


# ---- Spalten-Gruppierung ----
SURVEY_COLS: List[str] = [
    # *_Exp
    "QUANT1_Exp","QUANT2_Exp","QUANT3_Exp","QUAL1_Exp","QUAL2_Exp","QUAL3_Exp",
    "REL1_Exp","REL2_Exp","REL4_Exp","MAN1_Exp","MAN2_Exp","MAN3_Exp",
    "ANTRO1_Exp","ANTRO3_Exp","ANTRO4_Exp","LAT1_Exp","LAT2_Exp","LAT4_Exp",
    # Schlüssel
    "CHECK_CODE",
    # *_Per
    "QUANT1_Per","QUANT2_Per","QUANT3_Per","QUAL1_Per","QUAL2_Per","QUAL3_Per",
    "REL1_Per","REL2_Per","REL4_Per","MAN1_Per","MAN2_Per","MAN3_Per",
    "ANTRO1_Per","ANTRO3_Per","ANTRO4_Per","LAT1_Per","LAT2_Per","LAT4_Per",
]

JAEGER_COLS: List[str] = [
    "jaeger_found","jaeger_turns","jaeger_interruptions","jaeger_avg_turn_ms",
    "jaeger_latency","jaeger_visit_reason","jaeger_first_name","jaeger_last_name",
    "jaeger_phone","jaeger_chosen_slot","jaeger_slot_confirmed","jaeger_is_complete",
    "jaeger_text_response","jaeger_final_output",
]

REDIS_COLS: List[str] = [
    "redis_found","redis_call_id","redis_choosen_latency","redis_first_name","redis_last_name",
    "redis_phone","redis_visit_reason","redis_chosen_slot","redis_slot_confirmed",
    "redis_is_complete",
]

# Heuristik: welche Spalten sind „lange Texte“, die umgebrochen werden sollen?
# (alles mit diesen Mustern im Namen + explizite Kandidaten)
LONG_TEXT_HINTS = ("response", "history", "chat", "output", "text")
EXPLICIT_LONG_COLS = {"jaeger_text_response", "jaeger_final_output"}


# ---- CSV-Loading (robust) ----
def _clean_colname(col: str) -> str:
    if not isinstance(col, str):
        return col
    col = col.replace("\ufeff", "").strip()
    if len(col) >= 2 and ((col[0] == '"' and col[-1] == '"') or (col[0] == "'" and col[-1] == "'")):
        col = col[1:-1]
    return col.strip()


def _strip_quotes_from_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [_clean_colname(c) for c in df.columns]
    return df


def _detect_csv_params(path: str) -> Tuple[str, str]:
    import csv
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            sample = f.read(8192)
    except FileNotFoundError:
        raise
    if not sample:
        return ";", '"'
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=[",", ";", "\t", "|"])
        sep = dialect.delimiter
    except Exception:
        sep = ";"
    return sep, '"'


def load_csv_smart(path: str, sep_opt: Optional[str] = None,
                   quote_opt: Optional[str] = None, encoding_opt: str = "utf-8") -> pd.DataFrame:
    if sep_opt is None or quote_opt is None:
        det_sep, det_quote = _detect_csv_params(path)
        sep = sep_opt or det_sep
        quotechar = quote_opt or det_quote
    else:
        sep, quotechar = sep_opt, quote_opt

    try:
        df = pd.read_csv(path, sep=sep, quotechar=quotechar, encoding=encoding_opt, engine="python")
    except UnicodeDecodeError:
        df = pd.read_csv(path, sep=sep, quotechar=quotechar, encoding="latin1", engine="python")

    df = _strip_quotes_from_columns(df)

    if len(df.columns) == 1:
        try:
            df = pd.read_csv(path, sep=";", quotechar=quotechar, encoding=encoding_opt, engine="python")
        except UnicodeDecodeError:
            df = pd.read_csv(path, sep=";", quotechar=quotechar, encoding="latin1", engine="python")
        df = _strip_quotes_from_columns(df)

    return df


# ---- Formatierung ----
def is_long_text_col(col_name: str) -> bool:
    name = col_name.lower()
    return any(h in name for h in LONG_TEXT_HINTS) or (col_name in EXPLICIT_LONG_COLS)


def wrap_cell(val, width: int, max_lines: int) -> str:
    s = "" if pd.isna(val) else str(val)
    if width <= 0:
        return s
    # Weicher Umbruch, keine langen Wörter auseinanderreißen
    wrapped = textwrap.fill(s, width=width, break_long_words=False, break_on_hyphens=True)
    # ggf. Zeilen limitieren
    lines = wrapped.splitlines()
    if max_lines and len(lines) > max_lines:
        return "\n".join(lines[:max_lines] + ["…"])
    return wrapped


def format_table(df: pd.DataFrame, cols: Iterable[str], width: int, max_lines: int) -> pd.DataFrame:
    # Fehlt eine Spalte, leere Spalte ergänzen
    df_out = df.copy()
    real_cols = []
    # Case-insensitive Zuordnung
    ci_map = {c.upper(): c for c in df_out.columns}
    for c in cols:
        u = c.upper()
        real = ci_map.get(u, c)
        if real not in df_out.columns:
            df_out[real] = pd.NA
        real_cols.append(real)

    # Wrap für lange Textspalten
    for c in real_cols:
        if is_long_text_col(c):
            df_out[c] = df_out[c].map(lambda v: wrap_cell(v, width, max_lines))

    return df_out[real_cols]


def print_section(title: str):
    print()
    print("=" * len(title))
    print(title)
    print("=" * len(title))


def main():
    ap = argparse.ArgumentParser(description="Zeigt combined.csv in drei Tabellen (Umfrage / Jaeger / Redis) gut lesbar an.")
    ap.add_argument("--input", required=True, help="Pfad zu combined.csv")
    ap.add_argument("--head", type=int, default=None, help="Nur die ersten N Zeilen anzeigen")
    ap.add_argument("--width", type=int, default=100, help="Zeilenbreite für Umbruch langer Textfelder (Default: 100)")
    ap.add_argument("--max-lines", type=int, default=8, help="Max. Zeilen pro Zelle für lange Texte (Default: 8)")
    ap.add_argument("--sep", default=None, help="CSV Trennzeichen überschreiben (optional)")
    ap.add_argument("--quotechar", default=None, help="CSV Quotechar überschreiben (optional)")
    ap.add_argument("--encoding", default="utf-8", help="CSV Encoding (Default: utf-8)")
    args = ap.parse_args()

    try:
        df = load_csv_smart(args.input, args.sep, args.quotechar, args.encoding)
    except FileNotFoundError:
        print(f"[FATAL] Datei nicht gefunden: {args.input}", file=sys.stderr)
        sys.exit(1)

    if args.head:
        df = df.head(args.head)

    # Tabellen bauen
    survey_tbl = format_table(df, SURVEY_COLS, width=args.width, max_lines=args.max_lines)
    jaeger_tbl = format_table(df, JAEGER_COLS, width=args.width, max_lines=args.max_lines)
    redis_tbl  = format_table(df, REDIS_COLS,  width=args.width, max_lines=args.max_lines)

    # Ausgabe
    print_section("UMFRAGE")
    with pd.option_context("display.max_rows", None,
                           "display.max_columns", None,
                           "display.width", 0,
                           "display.max_colwidth", None):
        print(survey_tbl.to_string(index=False))

    print_section("JAEGER")
    with pd.option_context("display.max_rows", None,
                           "display.max_columns", None,
                           "display.width", 0,
                           "display.max_colwidth", None):
        print(jaeger_tbl.to_string(index=False))

    print_section("REDIS (redundant)")
    with pd.option_context("display.max_rows", None,
                           "display.max_columns", None,
                           "display.width", 0,
                           "display.max_colwidth", None):
        print(redis_tbl.to_string(index=False))


if __name__ == "__main__":
    main()
