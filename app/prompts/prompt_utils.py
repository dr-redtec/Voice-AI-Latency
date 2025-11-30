# prompt_utils.py
"""
Hilfsfunktionen zum Befüllen des System-Prompts für den Voice-Agent.
"""

from app.prompts.prompts import SYSTEM_PROMPTS
from app.config.config import get_settings

settings = get_settings()


def build_system_prompt(pin: str, var_slots: str) -> str:
    """
    Erstellt den System-Prompt mit Bestätigungs-PIN und Slot-Liste.

    Parameters
    ----------
    pin : str
        Vierstelliger Bestätigungscode, den der Agent am Ende ansagt.
    var_slots : str
        Kommagetrennte Auflistung der nächsten freien Termine,
        z. B. "Montag, 18.08., 09:00 Uhr, Dienstag, 19.08., 11:00 Uhr".

    Returns
    -------
    str
        Prompt-Text, bei dem die Platzhalter {VAR_PIN} und {VAR_SLOTS}
        im Template ersetzt wurden.
    """
    prompt_name = settings.system_prompt_name
    
    if prompt_name not in SYSTEM_PROMPTS:
        raise ValueError(f"Unknown system prompt: '{prompt_name}'")

    template = SYSTEM_PROMPTS[prompt_name]
    return template.format(VAR_PIN=pin, VAR_SLOTS=var_slots)