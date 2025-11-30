# slot_provider.py
# -----------------------------------------------------------
# Liefert freie Termine (Slots) & formatiert sie wahlweise
#   - tts=True  → "Montag, 28 Juli um 11 Uhr"
#   - tts=False → "Montag, 28.07., 11:00 Uhr"
# -----------------------------------------------------------

from datetime import datetime, timedelta, time
from typing import List, Dict
from num2words import num2words


# Feste deutsche Namen, damit wir LC_TIME nicht anfassen müssen
_WEEKDAYS_DE = [
    "Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag",
    "Samstag", "Sonntag",
]
_MONTHS_DE = [
    "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
]

def _de_ordinal_strong_masc(n: int) -> str:
    """17 -> 'siebzehnter' (stark, maskulin, wie bei '… siebzehnter September')."""
    w = num2words(n, lang="de", to="ordinal")   # z.B. 'siebzehnte'
    if w.endswith("ste"):
        return w[:-3] + "ster"
    if w.endswith("te"):
        return w[:-2] + "ter"
    return w

def _de_cardinal_for_clock(n: int) -> str:
    """9 -> 'neun', 1 -> 'ein' (für 'ein Uhr')."""
    if n == 1:
        return "ein"
    return num2words(n, lang="de")


class SlotProvider:
    """
    SlotProvider is a class for generating and managing time slots, typically used for scheduling purposes.
    Attributes:
        slots (List[Dict[str, datetime]]): A list of slot dictionaries, each containing a 'datetime' key.
    Methods:
        __init__(slots: List[Dict[str, datetime]]):
            Initializes the SlotProvider with a list of slot dictionaries.
        generate_slots(
            workdays=range(0, 5),
            times: List[time] = [time(9), time(11), time(14)]
        ) -> SlotProvider:
            Class method to generate slots for the upcoming weeks, on specified workdays and times.
        _format_label(dt: datetime, tts: bool = True) -> str:
            Static method to format a datetime object into a human-readable string, suitable for TTS or display.
        get_future_slots(
            max_n: int | None = None
            Returns a list of future slots, optionally limited by a time window and/or maximum number.
        var_slots_string(
            tts: bool = True
            Returns a formatted string of future slot labels, suitable for prompts or TTS output.
    """
    # -------------------- Initialisierung -------------------
    def __init__(self, slots: List[Dict[str, datetime]]):
        self.slots = slots

    # -------------------- Generator -------------------------
    @classmethod
    def generate_slots(
        cls,
        weeks_ahead: int = 4,
        workdays=range(0, 5),          # 0 = Montag … 4 = Freitag
        times: List[time] = [time(9), time(11), time(14)],
    ) -> "SlotProvider":
        """Erstellt Slots für die kommenden <weeks_ahead> Wochen ab morgen."""
        start_date = datetime.now().date() + timedelta(days=1)
        end_date   = start_date + timedelta(weeks=weeks_ahead)

        slots: List[Dict[str, datetime]] = []
        day = start_date
        while day <= end_date:
            if day.weekday() in workdays:
                for t in times:
                    dt = datetime.combine(day, t)
                    slots.append({"datetime": dt})
            day += timedelta(days=1)

        return cls(slots)

    # -------------------- Helfer: Label-Formatierung --------
    @staticmethod
    def _format_label(dt: datetime, tts: bool = True) -> str:
        """
        Baut einen String für den jeweiligen Slot.
        * tts=True  → 'Montag, 28 Juli um 11 Uhr'
        * tts=False → 'Montag, 28.07., 11:00 Uhr'
        """
        weekday = _WEEKDAYS_DE[dt.weekday()]            # Montag
        day     = dt.day                                # 28

        if tts:
            month  = _MONTHS_DE[dt.month - 1]
            hour   = dt.hour
            minute = dt.minute

            day_word  = _de_ordinal_strong_masc(dt.day)    # 17 -> 'siebzehnter'
            hour_word = _de_cardinal_for_clock(hour)         # 9 -> 'neun', 1 -> 'ein'

            if minute == 0:
                time_part = f"{hour_word} Uhr"
            else:
                # 1 Minute schönmachen
                minute_word = "eine" if minute == 1 else num2words(minute, lang="de")
                minute_unit = "Minute" if minute == 1 else "Minuten"
                time_part = f"{hour_word} Uhr {minute_word} {minute_unit}"

            return f"{weekday}, {day_word} {month} um {time_part}"
        else:
            # → 'Montag, 28.07., 11:00 Uhr'
            return f"{weekday}, {dt.strftime('%d.%m.')}, {dt.strftime('%H:%M')} Uhr"

    # -------------------- Filter: Zukunft / Fenster ---------
    def get_future_slots(
        self,
        within_days: int | None = None,
        max_n: int | None = None,
    ):
        """
        Gibt alle Slots in der Zukunft zurück.
        *within_days*   begrenzt das Zeitfenster (z. B. 7 → nächste Woche).
        *max_n*         begrenzt die Menge der zurückgegebenen Slots.
        """
        now = datetime.now()
        future = [s for s in self.slots if s["datetime"] > now]

        if within_days is not None:
            limit = now + timedelta(days=within_days)
            future = [s for s in future if s["datetime"] <= limit]

        return future[:max_n] if max_n else future

    # -------------------- Prompt-String ---------------------
    def var_slots_string(
        self,
        within_days: int = 7,
        max_n: int = 5,
        delimiter: str = ", ",
        tts: bool = True,
    ) -> str:
        """
        Liefert den Slot-String für den Prompt.
        Standard: *tts=True* für saubere Sprachausgabe.
        """
        labels = [
            self._format_label(s["datetime"], tts=tts)
            for s in self.get_future_slots(within_days, max_n)
        ]
        return delimiter.join(labels)


# -------------------- Testlauf -----------------------------
if __name__ == "__main__":
    provider = SlotProvider.generate_slots()
    print("TTS-freundlich:", provider.var_slots_string())          # Default (tts=True)
    print("Klassisch      :", provider.var_slots_string(tts=False))
