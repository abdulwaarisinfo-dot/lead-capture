"""
Everything that touches the model lives here: the client, the timeout, the
retry policy, cost logging, and the parse -> validate -> repair -> quarantine
loop. The route handler in index.py should never talk to the model directly.
"""
import os
import json
import time
import random
import logging
from pathlib import Path

from openai import OpenAI, APITimeoutError, APIStatusError
from pydantic import ValidationError

from llm.schema import TriageResult

logger = logging.getLogger("llm")

PROMPT_VERSION = "triage-v1"
PROMPT_PATH = Path(__file__).parent.parent / "prompts" / f"{PROMPT_VERSION}.md"
QUARANTINE_PATH = Path(__file__).parent.parent / "logs" / "quarantine.jsonl"
COST_LOG_PATH = Path(__file__).parent.parent / "logs" / "cost.jsonl"

TIMEOUT_SECONDS = 30.0
MAX_RETRIES_ON_TRANSIENT = 2  # timeouts / 429 / 5xx only — never on 400/401/403

_system_prompt_cache = None


def _load_system_prompt() -> str:
    global _system_prompt_cache
    if _system_prompt_cache is None:
        _system_prompt_cache = PROMPT_PATH.read_text()
    return _system_prompt_cache


def _client() -> OpenAI:
    return OpenAI(
        base_url=os.environ["LLM_BASE_URL"],
        api_key=os.environ["LLM_API_KEY"],
        timeout=TIMEOUT_SECONDS,
        max_retries=0,  # we implement our own retry policy below, not the SDK's
    )


def _log_cost(usage, duration_ms: float, repaired: bool):
    COST_LOG_PATH.parent.mkdir(exist_ok=True)
    line = {
        "prompt_version": PROMPT_VERSION,
        "model": os.environ.get("LLM_MODEL"),
        "input_tokens": getattr(usage, "prompt_tokens", None) if usage else None,
        "output_tokens": getattr(usage, "completion_tokens", None) if usage else None,
        "duration_ms": round(duration_ms, 1),
        "repaired": repaired,
    }
    with open(COST_LOG_PATH, "a") as f:
        f.write(json.dumps(line) + "\n")
    logger.info("llm_call %s", line)


def _quarantine(message: str, raw_output: str, error: str):
    QUARANTINE_PATH.parent.mkdir(exist_ok=True)
    line = {
        "prompt_version": PROMPT_VERSION,
        "input": message,
        "raw_output": raw_output,
        "error": error,
    }
    with open(QUARANTINE_PATH, "a") as f:
        f.write(json.dumps(line) + "\n")


def _extract_json(text: str) -> dict:
    """Models like to wrap JSON in a code fence or add chatty preamble. Strip
    that and find the object."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object found in model output")
    return json.loads(text[start:end + 1])


def _call_model_once(client: OpenAI, messages: list):
    """One call to the model, with our own retry-on-transient-errors policy
    (timeouts, 429, 5xx). Never retries on 400/401/403 — those will not fix
    themselves."""
    last_error = None
    for attempt in range(MAX_RETRIES_ON_TRANSIENT + 1):
        try:
            start = time.monotonic()
            resp = client.chat.completions.create(
                model=os.environ["LLM_MODEL"],
                messages=messages,
                temperature=0.2,
            )
            duration_ms = (time.monotonic() - start) * 1000
            return resp, duration_ms
        except APITimeoutError as e:
            last_error = e
        except APIStatusError as e:
            if e.status_code in (429,) or e.status_code >= 500:
                last_error = e
            else:
                # 400 / 401 / 403 and similar client errors: fail fast, no retry
                raise
        if attempt < MAX_RETRIES_ON_TRANSIENT:
            backoff = (2 ** attempt) + random.uniform(0, 0.5)
            time.sleep(backoff)
    raise last_error


def classify_message(message: str) -> TriageResult:
    """The whole pipeline: call -> parse -> validate -> repair once ->
    quarantine on final failure. Raises ValueError with a readable message on
    unrecoverable failure (route turns this into a 422/504)."""
    client = _client()
    system_prompt = _load_system_prompt()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": message},
    ]

    resp, duration_ms = _call_model_once(client, messages)
    raw_text = resp.choices[0].message.content
    _log_cost(resp.usage, duration_ms, repaired=False)

    try:
        parsed = _extract_json(raw_text)
        return TriageResult.model_validate(parsed)
    except (ValueError, ValidationError, json.JSONDecodeError) as first_error:
        # Repair retry: hand the model its own broken output + the exact error.
        repair_messages = messages + [
            {"role": "assistant", "content": raw_text},
            {
                "role": "user",
                "content": (
                    "Your previous answer was rejected for this reason: "
                    f"{first_error}. Return only corrected JSON matching the schema."
                ),
            },
        ]
        resp2, duration_ms2 = _call_model_once(client, repair_messages)
        raw_text2 = resp2.choices[0].message.content
        _log_cost(resp2.usage, duration_ms2, repaired=True)

        try:
            parsed2 = _extract_json(raw_text2)
            return TriageResult.model_validate(parsed2)
        except (ValueError, ValidationError, json.JSONDecodeError) as second_error:
            _quarantine(message, raw_text2, str(second_error))
            raise ValueError(f"model output failed validation twice: {second_error}")
