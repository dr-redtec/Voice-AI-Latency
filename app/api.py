from fastapi import FastAPI, Request, WebSocket

from pydantic import BaseModel
from app.services.telephony import build_call_client, answer_call
from contextlib import asynccontextmanager
import aiohttp
import asyncio

from app.services.container import make_services
from app.pipelines.call_pipeline import build_pipeline, run_pipeline

# ───────────────────────────── config ─────────────────────────────────────────
from app.config.config import get_settings
from app.config.logging_config import setup_logging

settings = get_settings()
setup_logging(settings)

# ───────────────────────────── lifespan ─────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manages the application's lifespan events by initializing and closing an aiohttp ClientSession.
    This function is intended to be used as a FastAPI lifespan handler. It creates an aiohttp.ClientSession
    and attaches it to the application's state for use during the app's lifetime. The session is properly
    closed when the application shuts down.
    Args:
        app (FastAPI): The FastAPI application instance.
    Yields:
        None
    Raises:
        Any exceptions raised during session creation or closure.
    """

    app.state.http_session = aiohttp.ClientSession()
    try:
        yield
    finally:
        await app.state.http_session.close()


 
# ───────────────────────────── clients ─────────────────────────────────────────
call_client = build_call_client(settings)

app          = FastAPI(lifespan=lifespan)

 
# ───────────────────────────── models ──────────────────────────────────────────
class IncomingCall(BaseModel):
    incomingCallContext: str
    dataVersion: str | None = None

async def _answer_after_delay(
    delay_s: float,
    call_client,
    incoming_call_context: str,
    callback_url: str,
    transport_url: str,
):
    try:
        await asyncio.sleep(delay_s)
        # identische Answer-Logik wie zuvor – nur verzögert
        from app.services.telephony import answer_call  # lokaler Import, um Zyklen zu vermeiden
        answer_call(
            call_client,
            incoming_call_context=incoming_call_context,
            callback_url=callback_url,
            transport_url=transport_url,
        )
    except Exception as e:
        import logging
        logging.getLogger("telephony").warning("delayed answer failed: %s", e)

 
# ───────────────────────────── endpoints ───────────────────────────────────────
@app.post("/incoming-call/")
async def incoming_call(request: Request):
    """
    Handles incoming call events from the request payload.
    This endpoint performs the following actions:
    1. Validates EventGrid subscription if the event type is 'SubscriptionValidationEvent'.
    2. Checks if the incoming call is intended for the configured ACS phone number.
    3. Answers the call and initiates media streaming if the call is valid.
    Args:
        request (Request): The incoming HTTP request containing the event payload.
    Returns:
        dict: A response indicating the result of the operation, such as subscription validation,
              call ignored, or call answered.
    """

    body = await request.json()
 
    # 1) subscription validation
    print("Call received:", body)
    if isinstance(body, list) and body and \
       body[0]["eventType"] == "Microsoft.EventGrid.SubscriptionValidationEvent":
        return {"validationResponse": body[0]["data"]["validationCode"]}
 
    ev  = body[0]
    if ev["data"]["to"]["phoneNumber"]["value"] != settings.acs_phone_number:
        print("Call ignored, not for us:")
        return {"status": "ignored"}
 
    incall = ev["data"]
    caller_id = ev["data"]["to"]["phoneNumber"]["value"][1:]
 
    # 2) answer the call with media streaming

    delay_s = settings.telephony_conf.ring_delay_s
    asyncio.create_task(_answer_after_delay(
        delay_s,
        call_client,
        incall["incomingCallContext"],
        settings.make_callback_url(caller_id),
        settings.media_stream_transport_url,
    ))
    return {"status": "answer_scheduled", "ring_delay_s": delay_s}


# ── /ws (nur Delegation) ─────────────────────────────────────────────────────
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    Handles incoming WebSocket connections and initiates the build_and_run_call process.
    Args:
        websocket (WebSocket): The WebSocket connection instance.
    Returns:
        None
    Raises:
        Any exceptions raised by build_and_run_call are propagated.
    """

    # 1) bauen
    services = make_services(settings, session=app.state.http_session)  # falls du Lifespan-Session nutzt

    artifacts = await build_pipeline(
        websocket=websocket,
        settings=settings,
        http_session=app.state.http_session,  # deine Lifespan-Session
        services=services,
    )
    # 2) laufen lassen
    await run_pipeline(artifacts)