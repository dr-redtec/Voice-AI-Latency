from typing import Optional, Dict, Any
from fastapi import WebSocket

# Pipecat Basics
from pipecat.transports.network.fastapi_websocket import (
    FastAPIWebsocketTransport, FastAPIWebsocketParams
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.pipeline.runner import PipelineRunner
from pipecat.processors.audio.audio_buffer_processor import AudioBufferProcessor
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import TTSSpeakFrame, EndFrame

from app.transports.acs_serializer import ACSFrameSerializer
from app.processors.turn_gate import TurnGateProcessor
from app.processors.stt_mute import build_stt_mute
from app.processors.latency_injector import LatencyInjector
from app.domain.slot_provider import SlotProvider
from app.providers.call_number_provider import CallNumberProvider
from app.domain.patient_tools import TOOLS_SCHEMA, handle_collect_patient_info, collect_patient_info_fn
from app.prompts.prompt_utils import build_system_prompt

# Services
from app.services.llm_client import build_llm
from app.services.stt_client import build_stt
from app.services.tts_client import build_tts
from app.services.container import Services, make_services
from app.services.redis_store import set_current_call_id, write_initial_call


# Tracing
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from pipecat.utils.tracing.setup import setup_tracing

from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
import aiohttp


async def build_pipeline(
    *,
    websocket: WebSocket,
    settings,
    http_session: Optional[aiohttp.ClientSession] = None,
    services: Optional[Services] = None,
) -> Dict[str, Any]:
    """
    Asynchronously builds and initializes the voice AI call pipeline.
    This function sets up the websocket connection, configures audio transport parameters,
    initializes latency injection, slot provider, tracing, and essential services (STT, LLM, TTS).
    It constructs the pipeline with all required processors, creates the pipeline task,
    registers event handlers for client connection/disconnection and audio data,
    and returns the pipeline runner and useful artifacts for further orchestration.
    Args:
        websocket (WebSocket): The FastAPI websocket connection to the client.
        settings: Configuration object containing pipeline, audio, latency, slot, and tracing settings.
        http_session (Optional[aiohttp.ClientSession], optional): Optional HTTP session for external service calls.
        services (Optional[Services], optional): Optional pre-initialized services (STT, LLM, TTS).
    Returns:
        Dict[str, Any]: Dictionary containing the transport, pipeline task, runner, pipeline,
                        services, processors, and context artifacts.
    Raises:
        Exception: Propagates exceptions from initialization or pipeline setup.
    """

    # 1) WS akzeptieren (wie gehabt)
    await websocket.accept()

    # 2) Transport / Params
    params = FastAPIWebsocketParams(
        audio_in_enabled=True,
        audio_out_enabled=True,
        audio_in_sample_rate=settings.ws_audio_in_sample_rate,
        audio_out_sample_rate=settings.ws_audio_out_sample_rate,
        serializer=ACSFrameSerializer(),
        session_timeout=settings.ws_session_timeout,
        vad_analyzer=SileroVADAnalyzer(),
    )
    transport = FastAPIWebsocketTransport(websocket, params)
    audiobuffer = AudioBufferProcessor()

    # 3) Deine Initialisierungen (identisch)
    latency = LatencyInjector(strategy=settings.latency.strategy)
    call_id = CallNumberProvider().get_number()

    chosen_latency = await latency._pick_latency()
    print(f"Session latency: {chosen_latency:.0f}s")

    set_current_call_id(call_id)

    await write_initial_call(
        call_id=call_id,
        choosen_latency=chosen_latency,            # exakt so benannt
        url=settings.redis.url,
        prefix=settings.redis.key_prefix,
        ttl_seconds=settings.redis.ttl_seconds,
    )

    provider  = SlotProvider.generate_slots(weeks_ahead=settings.slots.weeks_ahead)
    var_slots = provider.var_slots_string(
        within_days=settings.slots.var_within_days,
        max_n=settings.slots.var_max_n
    )
    print("Available slots:", var_slots)

    if settings.enable_tracing:
        otlp_exporter = OTLPSpanExporter(endpoint=settings.otel_endpoint, insecure=True)
        setup_tracing(
            service_name=settings.otel_service_name,
            exporter=otlp_exporter,
            console_export=bool(settings.otel_console_export),
        )

    # 4) Services
    services = services or make_services(settings, http_session)
    stt = services.stt
    stt_mute = build_stt_mute(stt, latency)
    llm = services.llm
    llm.register_function("collect_patient_info", handle_collect_patient_info)
    tts_service = services.tts

    # 5) Context / Aggregator
    context = OpenAILLMContext(
        messages=[{
            "role": "system",
            "content": build_system_prompt(call_id, var_slots),
        }],
        tools=TOOLS_SCHEMA,
        tool_choice="auto",
    )
    context_aggregator = llm.create_context_aggregator(context)

    turn_gate = TurnGateProcessor()

    # 6) Pipeline (Reihenfolge unverändert)
    pipeline = Pipeline([
        transport.input(),
        turn_gate,
        stt_mute,
        stt,
        context_aggregator.user(),
        latency,
        llm,
        tts_service,
        transport.output(),
        audiobuffer,
        context_aggregator.assistant(),
    ])

    string_latency = f"{latency.latency_seconds:.0f}" if latency.latency_seconds else "None"

    # 7) Task
    task_params = PipelineParams(enable_metrics=True, allow_interruptions=False)
    task = PipelineTask(
        pipeline,
        params=task_params,
        enable_tracing=True,
        enable_turn_tracking=True,
        conversation_id=f"{call_id}",
        additional_span_attributes={"latency": string_latency},
    )

    # 8) Event-Handler (identisch)
    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        print("Client connected")
        await task.queue_frames([
            TTSSpeakFrame("Guten Tag."),
            TTSSpeakFrame("Mein Name ist Kerstin – ich bin die digitale Assistentin der Hausarztpraxis Doktor Müller."),
            TTSSpeakFrame("Ich helfe Ihnen jetzt dabei, einen Termin zu vereinbaren."),

            TTSSpeakFrame("Vielen Dank, dass Sie an unserer wissenschaftlichen Studie teilnehmen."),
            TTSSpeakFrame("Bitte geben Sie für dieses Gespräch nicht Ihren echten Namen an."),
            TTSSpeakFrame("Bitte nutzen Sie erfundene Daten wie zum Beispiel »Max Mustermann« oder »Micki Maus«."),
            # TTSSpeakFrame("Da mehrere Anrufe gleichzeitig eingehen können, dauert meine Antwort manchmal ein paar Sekunden – bitte haben Sie etwas Geduld."),
            TTSSpeakFrame("Am Ende des Gesprächs nenne ich Ihnen eine dreistellige Umfrage-Nummer."),
            TTSSpeakFrame("Notieren Sie diese bitte und tragen Sie sie danach in die Umfrage ein."),

            # TTSSpeakFrame("So, ich glaube, wir sind bereit."),
            # TTSSpeakFrame("Sie können direkt loslegen – ich höre zu."),
            TTSSpeakFrame("Damit wir Sie bestmöglich einplanen können: Darf ich kurz fragen, weshalb Sie unsere Praxis aufsuchen möchten?"),
            # TTSSpeakFrame(
            #     "Legen wir los!"
            # ),
            # TTSSpeakFrame(
            #     "Guten Tag! Ich bin der digitale, KI-gestützte Termin-Assistent einer Praxis. Vielen Dank, dass Sie an unserer wissenschaftlichen Studie teilnehmen. Bitte geben Sie für dieses Gespräch nicht Ihren echten Namen an. Bitte nutzen Sie erfundene Daten wie zum Beispiel »Max Mustermann« oder »Mickey Mouse«. Da mehrere Anrufe gleichzeitig eingehen können, dauert meine Antwort manchmal ein paar Sekunden – bitte haben Sie etwas Geduld. Am Ende des Gesprächs nenne ich Ihnen eine dreistellige PROLIFIC-Nummer. Notieren Sie diese bitte und tragen Sie sie danach in die Umfrage ein."
            # ),
        ])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        print("Client disconnected")
        await task.cancel()

    @audiobuffer.event_handler("on_audio_data")
    async def on_audio_data(buffer, audio, sample_rate, num_channels):
        print(f"Received audio data: {len(audio)} bytes, {sample_rate}Hz, {num_channels} channels")

    # 9) Runner erzeugen (NICHT starten)
    runner = PipelineRunner(handle_sigint=False, force_gc=True)

    return {
        "transport": transport,
        "task": task,
        "runner": runner,
        # optional nützliche Artefakte:
        "pipeline": pipeline,
        "services": services,
        "processors": {"turn_gate": turn_gate, "latency": latency},
        "context": {"openai": context, "aggregator": context_aggregator, "call_id": call_id},
    }


async def run_pipeline(artifacts: Dict[str, Any]) -> None:
    """
    Runs the provided pipeline task asynchronously using the specified runner.
    Args:
        artifacts (Dict[str, Any]): A dictionary containing the pipeline artifacts, 
            expected to include "runner" (an object with a `run` coroutine method) and 
            "task" (an object representing the task to be run).
    This function attempts to run the given task using the runner. If the task is not 
    cancelled after execution (e.g., if the client disconnects during processing), it 
    attempts to cancel the task in an idempotent manner. Any exceptions raised during 
    cancellation are suppressed.
    """
    
    runner = artifacts["runner"]
    task   = artifacts["task"]

    try:
        await runner.run(task)
    finally:
        # idempotent cancel, falls der Client während TTS/LLM auflegt
        if hasattr(task, "is_cancelled") and not task.is_cancelled():
            try:
                await task.cancel()
            except Exception:
                pass
