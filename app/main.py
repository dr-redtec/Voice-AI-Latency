import uvicorn
from app.config.config import get_settings
from app.services.stt_client import build_stt


def main():
    """
    Initializes application settings, builds the speech-to-text (STT) model, prints a confirmation message,
    and starts the FastAPI server using Uvicorn with the specified host and port from settings.
    """

    settings = get_settings()
    build_stt(settings)
    print("✅ Whisper STT Modell warmgeladen")
    uvicorn.run("app.api:app", host=settings.host, port=settings.port, reload=False)

if __name__ == "__main__":
    main()