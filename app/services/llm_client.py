from app.config.config import Settings
from pipecat.services.azure.llm import AzureLLMService

def build_llm(settings: Settings) -> AzureLLMService:
    """
    
    Constructs and returns an instance of AzureLLMService configured with the provided settings.
    Args:
        settings (Settings): Configuration object containing Azure OpenAI credentials, model name, and LLM parameters.
    Returns:
        AzureLLMService: An initialized AzureLLMService object ready for use with the specified settings.
    """
    return AzureLLMService(
        api_key=settings.azure_openai_key,
        endpoint=settings.azure_openai_endpoint,
        model=settings.azure_openai_model,
        params=AzureLLMService.InputParams(
            temperature=settings.llm_temperature,
            max_completion_tokens=settings.llm_max_tokens,
        ),
    )
