from langchain_core.language_models import BaseChatModel

from backend.llm.providers.mock_llm import get_mock_llm

def get_llm() -> BaseChatModel:
    return get_mock_llm()