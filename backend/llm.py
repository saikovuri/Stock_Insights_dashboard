"""Thin wrapper around OpenAI-compatible chat APIs (Gemini, Groq, OpenAI) with cross-provider fallback."""

import json
import logging
import re
import time

from openai import OpenAI, BadRequestError, APIStatusError, APIConnectionError

from config import AI_API_KEY, AI_REASONING_EFFORT, AI_CHAIN

log = logging.getLogger(__name__)

_RETRYABLE_STATUS = {401, 403, 404, 429, 500, 502, 503, 504}
# Whole-chain budget; hosting proxies (Render) drop requests after ~100s
CHAT_BUDGET_S = 50
MIN_ATTEMPT_S = 8
# One slow/overloaded provider must not eat the whole budget before the next one gets a turn
MAX_ATTEMPT_S = 20
_LIGHT_HINTS = ("lite", "20b", "mini", "8b")

_clients: dict[str, OpenAI] = {}
# Models that rejected the reasoning_effort parameter
_no_reasoning: set[str] = set()
# model -> monotonic time until which it's skipped (after rate limits / quota exhaustion)
_cooldown: dict[str, float] = {}


def ai_enabled() -> bool:
    return bool(AI_API_KEY)


def _get_client(api_key: str, base_url: str | None) -> OpenAI:
    key = f"{base_url}|{api_key[-6:]}"
    if key not in _clients:
        # No SDK retries: they sleep on Retry-After, while the next model in the chain can answer now
        kwargs = {"api_key": api_key, "timeout": 45, "max_retries": 0}
        if base_url:
            kwargs["base_url"] = base_url
        _clients[key] = OpenAI(**kwargs)
    return _clients[key]


def _portable(messages: list[dict]) -> list[dict]:
    """Drop provider-specific extras (e.g. Gemini thought signatures) before sending elsewhere."""
    out = []
    for m in messages:
        clean = {k: m[k] for k in ("role", "content", "tool_call_id", "name") if k in m}
        if m.get("tool_calls"):
            clean["tool_calls"] = [{"id": c["id"], "type": "function",
                                   "function": {"name": c["function"]["name"],
                                                "arguments": c["function"].get("arguments") or "{}"}}
                                  for c in m["tool_calls"]]
        out.append(clean)
    return out


def chat(messages: list[dict], *, json_mode: bool = False, tools: list | None = None,
         tool_choice: str | None = None, temperature: float = 0.2, max_tokens: int = 1500,
         budget_s: float = CHAT_BUDGET_S, light: bool = False):
    """Return the first choice's message, trying each provider/model in AI_CHAIN until one answers.
    light=True tries the smaller models first (saves the main models' daily quota for briefs/chat)."""
    attempts = [(name, key, url, model) for name, key, url, models in AI_CHAIN for model in models]
    if light:
        attempts.sort(key=lambda a: not any(h in a[3] for h in _LIGHT_HINTS))
    now = time.monotonic()
    deadline = now + budget_s
    ready = [a for a in attempts if _cooldown.get(a[3], 0) <= now]
    # If everything is cooling down, try them all anyway rather than failing outright
    attempts = ready or attempts
    last_err = None
    for i, (name, key, url, model) in enumerate(attempts):
        remaining = deadline - time.monotonic()
        if remaining < MIN_ATTEMPT_S and last_err is not None:
            log.warning("AI time budget exhausted after %d attempt(s)", i)
            break
        msgs = messages if i == 0 or url == attempts[0][2] else _portable(messages)
        client = _get_client(key, url).with_options(timeout=min(max(remaining, MIN_ATTEMPT_S), MAX_ATTEMPT_S))
        try:
            return _chat_once(client, model, msgs, json_mode, tools, tool_choice,
                              temperature, max_tokens)
        except (APIStatusError, APIConnectionError) as e:
            status = getattr(e, "status_code", None)
            if status is not None and status not in _RETRYABLE_STATUS:
                raise
            if status == 429:
                # Daily quota exhaustion won't clear soon; per-minute limits will
                _cooldown[model] = time.monotonic() + (1800 if "quota" in str(e).lower() else 90)
            elif status in (401, 403, 404):
                _cooldown[model] = time.monotonic() + 3600
            elif status == 503:
                # "Model overloaded": give it a few minutes instead of paying the latency every request
                _cooldown[model] = time.monotonic() + 300
            elif status is None:
                # Timeout / connection error: skip this model briefly so the next request goes elsewhere
                _cooldown[model] = time.monotonic() + 120
            last_err = e
            if i + 1 < len(attempts):
                log.warning("AI %s/%s failed (%s); trying %s/%s", name, model, status or "connection",
                            attempts[i + 1][0], attempts[i + 1][3])
    raise last_err


def _chat_once(client, model, messages, json_mode, tools, tool_choice, temperature, max_tokens):
    kwargs = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    if tools:
        kwargs["tools"] = tools
        if tool_choice:
            kwargs["tool_choice"] = tool_choice
    if AI_REASONING_EFFORT and model not in _no_reasoning:
        kwargs["reasoning_effort"] = AI_REASONING_EFFORT

    try:
        resp = client.chat.completions.create(**kwargs)
    except BadRequestError as e:
        if "reasoning_effort" in kwargs and "reason" in str(e).lower():
            log.info("Model %s does not accept reasoning_effort; disabling it", model)
            _no_reasoning.add(model)
            kwargs.pop("reasoning_effort")
            resp = client.chat.completions.create(**kwargs)
        else:
            raise
    return resp.choices[0].message


def chat_json(system: str, user: str, *, temperature: float = 0.2, max_tokens: int = 1500,
              budget_s: float = CHAT_BUDGET_S, light: bool = False) -> dict:
    """Ask for a JSON object; retries once with a stricter reminder if parsing fails."""
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    last_err = None
    deadline = time.monotonic() + budget_s
    for _ in range(2):
        remaining = deadline - time.monotonic()
        if last_err is not None and remaining < MIN_ATTEMPT_S:
            break
        msg = chat(messages, json_mode=True, temperature=temperature, max_tokens=max_tokens, budget_s=remaining,
                   light=light)
        try:
            return parse_json(msg.content or "")
        except ValueError as e:
            last_err = e
            messages.append({"role": "assistant", "content": msg.content or ""})
            messages.append({"role": "user", "content": "That was not valid JSON. Reply with ONLY the JSON object."})
    raise ValueError(f"Model did not return valid JSON: {last_err}")


def parse_json(text: str) -> dict:
    cleaned = text.strip().replace("```json", "").replace("```", "").strip()
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        raise ValueError("No JSON object found")
    cleaned = re.sub(r",\s*([}\]])", r"\1", match.group(0))
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(str(e)) from e
    if not isinstance(data, dict):
        raise ValueError("JSON root is not an object")
    return data
