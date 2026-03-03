"""LLM 인스턴스 정의."""
from backend import config
from langchain_ollama import ChatOllama

llm = ChatOllama(
    model=config.LLM_MODEL,
    streaming=True,
    temperature=config.LLM_TEMPERATURE,
)

