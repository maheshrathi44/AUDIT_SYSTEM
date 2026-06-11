"""
LLM client — works with any OpenAI-compatible API.
Reads config from .env file in project root (or environment variables).

Provider setup (set in .env):
  OpenAI   → AUDIT_BASE_URL=https://api.openai.com/v1
              AUDIT_MODEL=gpt-4o-mini

  Gemini   → AUDIT_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
              AUDIT_MODEL=gemini-2.0-flash

  Groq     → AUDIT_BASE_URL=https://api.groq.com/openai/v1
              AUDIT_MODEL=llama-3.3-70b-versatile
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

# Load .env from project root (two levels up from this file)
_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(_env_path)


def _client() -> OpenAI:
    api_key  = os.environ.get("AUDIT_API_KEY", "")
    base_url = os.environ.get("AUDIT_BASE_URL", "https://api.openai.com/v1")
    if not api_key:
        raise RuntimeError(
            "\nAUDIT_API_KEY not set.\n"
            "Add it to your .env file:\n"
            "  AUDIT_API_KEY=your_key_here\n"
        )
    return OpenAI(api_key=api_key, base_url=base_url)


def get_model() -> str:
    return os.environ.get("AUDIT_MODEL", "gpt-4o-mini")


def chat(messages: list[dict], *, json_mode: bool = False) -> str:
    """Call LLM and return response text."""
    kwargs: dict = {}
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    resp = _client().chat.completions.create(
        model=get_model(),
        messages=messages,
        temperature=0,
        **kwargs,
    )
    return resp.choices[0].message.content or ""
