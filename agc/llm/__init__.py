"""LLM调用层 — 统一接口，直接用OpenAI SDK"""

from .base import LLMBase
from .openai_client import OpenAIClient

__all__ = ["LLMBase", "OpenAIClient"]