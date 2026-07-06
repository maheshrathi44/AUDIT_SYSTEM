"""
LLM client — works with any OpenAI-compatible API.
Reads config from .env file in project root (or environment variables).

Provider setup (set in .env):
  OpenAI      → AUDIT_BASE_URL=https://api.openai.com/v1
                AUDIT_MODEL=gpt-4o-mini

  Gemini      → AUDIT_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
                AUDIT_MODEL=gemini-2.0-flash

  Groq        → AUDIT_BASE_URL=https://api.groq.com/openai/v1
                AUDIT_MODEL=llama-3.3-70b-versatile

  Databricks  → AUDIT_BASE_URL=https://<workspace>/serving-endpoints
                AUDIT_MODEL=databricks-gemini-2-5-flash

Corporate network options (add to .env if needed):
  HTTPS_PROXY=http://proxy.company.com:8080   ← set if behind a proxy
  AUDIT_SSL_VERIFY=0                          ← disable SSL verification if proxy intercepts HTTPS
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx
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

    # SSL verification — disable if corporate proxy intercepts HTTPS (AUDIT_SSL_VERIFY=0)
    ssl_raw    = os.environ.get("AUDIT_SSL_VERIFY", "1").strip().lower()
    ssl_verify = ssl_raw not in ("0", "false", "no")

    # Proxy — reads HTTPS_PROXY / HTTP_PROXY from .env or system environment
    proxy = (
        os.environ.get("HTTPS_PROXY")
        or os.environ.get("HTTP_PROXY")
        or None
    )

    http_client = httpx.Client(verify=ssl_verify, proxy=proxy)
    return OpenAI(api_key=api_key, base_url=base_url, http_client=http_client)


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
