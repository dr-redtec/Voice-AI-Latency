from app.config.config import Settings
from azure.communication.callautomation import (
    CallAutomationClient,
    MediaStreamingOptions, MediaStreamingTransportType,
    MediaStreamingContentType, MediaStreamingAudioChannelType, AudioFormat,
)

def build_call_client(settings: Settings) -> CallAutomationClient:
    """
    Creates and returns a CallAutomationClient instance using the provided settings.
    Args:
        settings (Settings): An object containing configuration, including the ACS connection string.
    Returns:
        CallAutomationClient: An initialized client for call automation operations.
    """

    return CallAutomationClient.from_connection_string(settings.acs_connection_string)

def answer_call(call_client: CallAutomationClient, *, incoming_call_context: str, callback_url: str, transport_url: str):
    """
    Answers an incoming call and starts media streaming with specified options.
    Args:
        call_client (CallAutomationClient): The client used to handle call automation.
        incoming_call_context (str): The context identifier for the incoming call.
        callback_url (str): The URL to receive call event callbacks.
        transport_url (str): The URL used for media streaming transport.
    Returns:
        The result of the answer_call operation from the call_client.
    Raises:
        Any exceptions raised by the underlying call_client.answer_call method.
    """

    return call_client.answer_call(
        incoming_call_context=incoming_call_context,
        callback_url=callback_url,
        media_streaming=MediaStreamingOptions(
            transport_url=transport_url,
            transport_type=MediaStreamingTransportType.WEBSOCKET,
            content_type=MediaStreamingContentType.AUDIO,
            audio_channel_type=MediaStreamingAudioChannelType.UNMIXED,
            audio_format=AudioFormat.PCM16_K_MONO,
            start_media_streaming=True,
            enable_bidirectional=True,
        ),
    )
