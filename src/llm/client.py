"""
llm/client.py — LLM Wrapper

Single place for all LLM calls. Nodes never call Azure OpenAI directly.
Switching from Azure → OpenAI → Claude = change only this file.
"""

import json
import re
from langchain_openai import AzureChatOpenAI
import config


class LLMClient:
    """Thin wrapper around Azure OpenAI. Three call modes: text, json, structured."""

    def __init__(self):
        self._llm = AzureChatOpenAI(
            azure_endpoint=config.LLM_ENDPOINT,
            api_key=config.LLM_API_KEY,
            azure_deployment=config.LLM_DEPLOYMENT,
            api_version=config.LLM_API_VERSION,
            temperature=0,          # deterministic — important for intent/entity extraction
        )

    def invoke(self, messages: list) -> str:
        """Call LLM and return the text content of the response."""
        response = self._llm.invoke(messages)
        return response.content.strip()

    def json_output(self, messages: list) -> dict:
        """
        Call LLM and parse a JSON object from the response.
        Handles cases where the model wraps JSON in markdown code blocks.
        """
        raw = self.invoke(messages)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # Strip markdown code fences if present: ```json ... ```
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
        return {}   # safe fallback — never raises

    def structured_output(self, messages: list, schema):
        """
        Call LLM with a Pydantic schema for guaranteed structured output.
        Use this when you need a typed response object instead of a dict.
        """
        return self._llm.with_structured_output(schema).invoke(messages)
