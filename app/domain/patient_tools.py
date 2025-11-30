# patient_tools.py
import logging
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.services.llm_service import FunctionCallParams, FunctionCallResultProperties
from app.config.config import get_settings
from app.services.redis_store import get_current_call_id, update_patient_fields

log = logging.getLogger(__name__)

# --- 1) Funktions-Schema -------------------------------------------
collect_patient_info_fn = FunctionSchema(
    name="collect_patient_info",
    description="Strukturiere Informationen des Patienten für die Termin Findung.",
    properties={
        "visit_reason": {"type": "string", "description": "Grund des Besuchs"},
        "first_name":   {"type": "string", "description": "Vorname"},
        "last_name":    {"type": "string", "description": "Nachname"},
        "phone":        {"type": "string", "description": "Telefonnummer"},
        "chosen_slot":   {"type": "string",  "description": "Ausgewählter Termin (Slot)"},
        "slot_confirmed":{"type": "boolean","description": "Termin vom Patienten bestätigt?"},
        "is_complete":  {"type": "boolean","description": "Alle Infos erfasst?"},
        "text_response":{"type": "string", "description": "Antwort an den Patienten"}
    },
    required=["is_complete", "text_response"]
)

TOOLS_SCHEMA = ToolsSchema(standard_tools=[collect_patient_info_fn])

# --- 2) Handler ------------------------------------------------------
# Du kannst hier gern Redis etc. einbinden, z. B. wie in openai_client.py
async def handle_collect_patient_info(params: FunctionCallParams):
    """
    Asynchronously handles the collection of patient information from the provided parameters.
    Logs received patient data and details for debugging purposes. Intended to store the data
    in a persistent storage (e.g., Redis or database), but actual storage implementation is pending.
    Returns a status result to the caller via the provided callback, allowing further processing.
    Args:
        params (FunctionCallParams): Parameters containing patient information and a result callback.
    Returns:
        None
    Raises:
        None
    """
    data = params.arguments  # genau die Felder oben
    log.info("📦 Patientendaten erhalten: %s", data)
    
    log.debug(
        "Patient: %s %s | Tel: %s | Grund: %s | Vollständig: %s",
        data.get("first_name"),
        data.get("last_name"),
        data.get("phone"),
        data.get("visit_reason"),
        data.get("chosen_slot"),
        data.get("slot_confirmed"),
        data.get("is_complete"),
    )

    # TODO: hier ablegen (Redis, DB …) -------------------------------
    settings = get_settings()
    call_id = get_current_call_id()
    if call_id:
        await update_patient_fields(
            call_id=call_id,
            url=settings.redis.url,
            prefix=settings.redis.key_prefix,
            ttl_seconds=settings.redis.ttl_seconds,
            # genau deine Zielfelder:
            first_name=data.get("first_name"),
            last_name=data.get("last_name"),
            phone=data.get("phone"),
            visit_reason=data.get("visit_reason"),
            chosen_slot=data.get("chosen_slot"),
            slot_confirmed=data.get("slot_confirmed"),
            is_complete=data.get("is_complete"),
        )
    else:
        log.warning("⚠️ Kein call_id im Kontext – Redis-Write übersprungen.")

    # Ergebnis an LLM zurückgeben – danach darf er normal weiter­reden
    await params.result_callback(
        {"status": "received"},
        properties=FunctionCallResultProperties(run_llm=True)
    )
    