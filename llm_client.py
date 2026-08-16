"""
LLM-Adapter fuer Wingcast.

Stellt einen Provider-agnostischen Wrapper bereit, der die OpenAI-kompatible
Schnittstelle `client.chat.completions.create(...)` exponiert und intern auf
OpenAI, Anthropic, Google Gemini oder DeepSeek dispatcht.

DeepSeek nutzt eine OpenAI-kompatible API → dispatcht auf den OpenAI-SDK
mit `base_url="https://api.deepseek.com"` (kein eigener Adapter noetig).

Vorteile:
  - Engine-Code (chat_orchestrator.py, analyzers.py) bleibt unveraendert,
    nur die Client-Instanz wechselt.
  - Response-Objekte sind duck-kompatibel zu OpenAI:
      response.choices[0].message.content
      response.choices[0].message.tool_calls[i].{id, function.name, function.arguments}
      response.choices[0].finish_reason
      response.usage.prompt_tokens
      response.usage.prompt_tokens_details.cached_tokens

Einschraenkungen:
  - Streaming wird nicht noetig (Engine nutzt non-streaming Calls).
  - Batch-API nur fuer OpenAI. Aufrufer muss den Provider pruefen und bei
    Bedarf auf parallel umschalten.
  - JSON-Mode:
      openai    → response_format={"type":"json_object"}
      anthropic → System-Prompt-Append + JSON-Parsing + Fence-Stripping
      gemini    → response_mime_type="application/json"
"""

from __future__ import annotations

import json
import logging
import re
from types import SimpleNamespace
from typing import Any, Iterable

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Duck-type shim fuer OpenAI-kompatible Responses
# ─────────────────────────────────────────────────────────────────────────────
def _make_tool_call(tc_id: str, name: str, arguments_json: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=tc_id,
        type="function",
        function=SimpleNamespace(name=name, arguments=arguments_json),
    )


def _make_response(
    content: str,
    tool_calls: list | None = None,
    finish_reason: str = "stop",
    prompt_tokens: int = 0,
    cached_tokens: int = 0,
    completion_tokens: int = 0,
) -> SimpleNamespace:
    """Baut ein OpenAI-shaped Response-Objekt."""
    msg = SimpleNamespace(
        role="assistant",
        content=content or "",
        tool_calls=tool_calls if tool_calls else None,
    )
    usage = SimpleNamespace(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
        prompt_tokens_details=SimpleNamespace(cached_tokens=cached_tokens),
    )
    return SimpleNamespace(
        choices=[SimpleNamespace(message=msg, finish_reason=finish_reason)],
        usage=usage,
    )


# ─────────────────────────────────────────────────────────────────────────────
# JSON-Extraktion (fuer Provider ohne nativen JSON-Mode)
# ─────────────────────────────────────────────────────────────────────────────
_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)


def _strip_json_fence(text: str) -> str:
    """Entfernt ```json ... ``` Fences aus LLM-Output, falls vorhanden."""
    if not text:
        return text
    s = text.strip()
    if s.startswith("```"):
        s = _JSON_FENCE_RE.sub("", s).strip()
    return s


# ─────────────────────────────────────────────────────────────────────────────
# Anthropic-Adapter
# ─────────────────────────────────────────────────────────────────────────────
def _openai_tools_to_anthropic(tools: list) -> list:
    """Konvertiert OpenAI-Tool-Schema → Anthropic input_schema."""
    out = []
    for t in tools or []:
        if t.get("type") != "function":
            continue
        fn = t.get("function", {})
        out.append({
            "name": fn.get("name"),
            "description": fn.get("description", ""),
            "input_schema": fn.get("parameters") or {"type": "object", "properties": {}},
        })
    return out


def _openai_messages_to_anthropic(messages: list) -> tuple[str, list]:
    """Trennt OpenAI-Messages in (system_prompt, anthropic_messages).

    - role=system → wird zusammengefuehrt als top-level system-Parameter
    - role=tool   → umgewandelt in user-message mit tool_result content-block
    - tool_calls in assistant → umgewandelt in tool_use content-blocks
    """
    system_parts = []
    out = []
    for m in messages:
        role = m.get("role")
        content = m.get("content", "")

        if role == "system":
            if content:
                system_parts.append(content if isinstance(content, str) else str(content))
            continue

        if role == "tool":
            # OpenAI: {"role": "tool", "tool_call_id": ..., "name": ..., "content": "..."}
            out.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": m.get("tool_call_id") or "",
                    "content": content if isinstance(content, str) else json.dumps(content, ensure_ascii=False),
                }],
            })
            continue

        if role == "assistant":
            tool_calls = m.get("tool_calls") or []
            blocks = []
            if content:
                blocks.append({"type": "text", "text": content if isinstance(content, str) else str(content)})
            for tc in tool_calls:
                fn = tc.get("function", {}) if isinstance(tc, dict) else {}
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except (json.JSONDecodeError, TypeError):
                    args = {}
                blocks.append({
                    "type": "tool_use",
                    "id": tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", ""),
                    "name": fn.get("name", ""),
                    "input": args,
                })
            if not blocks:
                blocks = [{"type": "text", "text": ""}]
            out.append({"role": "assistant", "content": blocks})
            continue

        if role == "user":
            out.append({
                "role": "user",
                "content": content if isinstance(content, str) else json.dumps(content, ensure_ascii=False),
            })
            continue

    return "\n\n".join(system_parts), out


def _anthropic_response_to_openai(resp, json_mode: bool = False) -> SimpleNamespace:
    """Konvertiert anthropic.Message → OpenAI-shaped response."""
    content_text = ""
    tool_calls = []
    for block in getattr(resp, "content", []) or []:
        btype = getattr(block, "type", None)
        if btype == "text":
            content_text += getattr(block, "text", "") or ""
        elif btype == "tool_use":
            tool_calls.append(_make_tool_call(
                tc_id=getattr(block, "id", ""),
                name=getattr(block, "name", ""),
                arguments_json=json.dumps(getattr(block, "input", {}) or {}, ensure_ascii=False),
            ))

    if json_mode and content_text:
        content_text = _strip_json_fence(content_text)

    stop_reason = getattr(resp, "stop_reason", "end_turn")
    finish_reason = "tool_calls" if tool_calls else (
        "stop" if stop_reason in ("end_turn", "stop_sequence") else "length"
    )

    usage = getattr(resp, "usage", None)
    prompt_tokens = getattr(usage, "input_tokens", 0) if usage else 0
    # Anthropic Prompt-Caching: cache_read_input_tokens zaehlt als Hit
    cached = getattr(usage, "cache_read_input_tokens", 0) if usage else 0
    completion_tokens = getattr(usage, "output_tokens", 0) if usage else 0
    # Anthropic meldet cached_tokens separat — fuer Konsistenz mit OpenAI
    # addieren wir sie in prompt_tokens, falls nicht schon inkludiert.
    return _make_response(
        content=content_text,
        tool_calls=tool_calls or None,
        finish_reason=finish_reason,
        prompt_tokens=prompt_tokens + cached,
        cached_tokens=cached,
        completion_tokens=completion_tokens,
    )


def _call_anthropic(
    raw_client,
    model: str,
    messages: list,
    temperature: float = 1.0,
    max_tokens: int = 1024,
    tools: list | None = None,
    tool_choice: str | dict | None = None,
    response_format: dict | None = None,
) -> SimpleNamespace:
    system, a_messages = _openai_messages_to_anthropic(messages)
    json_mode = (response_format or {}).get("type") == "json_object"
    if json_mode:
        hint = (
            "Antworte AUSSCHLIESSLICH mit einem einzigen, validen JSON-Objekt. "
            "Kein Markdown, keine Code-Fences, kein erklaerender Text davor oder danach."
        )
        system = (system + "\n\n" + hint).strip() if system else hint

    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": a_messages,
    }
    if system:
        kwargs["system"] = system
    if tools:
        kwargs["tools"] = _openai_tools_to_anthropic(tools)
        if tool_choice == "auto":
            kwargs["tool_choice"] = {"type": "auto"}
        elif tool_choice == "required":
            kwargs["tool_choice"] = {"type": "any"}
        elif isinstance(tool_choice, dict):
            # OpenAI: {"type":"function","function":{"name":"..."}}
            fn = tool_choice.get("function") or {}
            if fn.get("name"):
                kwargs["tool_choice"] = {"type": "tool", "name": fn["name"]}

    resp = raw_client.messages.create(**kwargs)
    return _anthropic_response_to_openai(resp, json_mode=json_mode)


# ─────────────────────────────────────────────────────────────────────────────
# Gemini-Adapter (google-genai SDK)
# ─────────────────────────────────────────────────────────────────────────────
def _openai_messages_to_gemini(messages: list) -> tuple[str, list]:
    """Trennt OpenAI-Messages in (system_instruction, gemini_contents).

    Gemini Roles: "user" | "model".
    Tool-Calls/-Results werden als FunctionCall/FunctionResponse-Parts gemappt.
    """
    system_parts = []
    contents = []
    for m in messages:
        role = m.get("role")
        content = m.get("content", "")

        if role == "system":
            if content:
                system_parts.append(content if isinstance(content, str) else str(content))
            continue

        if role == "tool":
            # OpenAI tool message → Gemini function_response
            try:
                data = json.loads(content) if isinstance(content, str) else content
            except (json.JSONDecodeError, TypeError):
                data = {"result": content}
            contents.append({
                "role": "user",
                "parts": [{
                    "function_response": {
                        "name": m.get("name") or "tool",
                        "response": data if isinstance(data, dict) else {"result": data},
                    }
                }],
            })
            continue

        if role == "assistant":
            parts = []
            if content:
                parts.append({"text": content if isinstance(content, str) else str(content)})
            for tc in (m.get("tool_calls") or []):
                fn = tc.get("function", {}) if isinstance(tc, dict) else {}
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except (json.JSONDecodeError, TypeError):
                    args = {}
                parts.append({"function_call": {"name": fn.get("name", ""), "args": args}})
            if not parts:
                parts = [{"text": ""}]
            contents.append({"role": "model", "parts": parts})
            continue

        if role == "user":
            contents.append({
                "role": "user",
                "parts": [{"text": content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)}],
            })
            continue

    return "\n\n".join(system_parts), contents


def _openai_tools_to_gemini(tools: list) -> list:
    """Konvertiert OpenAI-Tool-Schema → Gemini function_declarations."""
    decls = []
    for t in tools or []:
        if t.get("type") != "function":
            continue
        fn = t.get("function", {})
        decls.append({
            "name": fn.get("name"),
            "description": fn.get("description", ""),
            "parameters": fn.get("parameters") or {"type": "object", "properties": {}},
        })
    return [{"function_declarations": decls}] if decls else []


def _gemini_response_to_openai(resp, json_mode: bool = False) -> SimpleNamespace:
    candidates = getattr(resp, "candidates", []) or []
    content_text = ""
    tool_calls = []
    finish_reason_raw = ""
    if candidates:
        cand = candidates[0]
        finish_reason_raw = str(getattr(cand, "finish_reason", "") or "").upper()
        content_obj = getattr(cand, "content", None)
        parts = getattr(content_obj, "parts", []) if content_obj else []
        for i, part in enumerate(parts or []):
            txt = getattr(part, "text", None)
            fc = getattr(part, "function_call", None)
            if txt:
                content_text += txt
            if fc:
                name = getattr(fc, "name", "") or ""
                args = getattr(fc, "args", None) or {}
                # args kann MapComposite oder dict sein → in echtes dict wandeln
                try:
                    args_dict = dict(args) if args else {}
                except (TypeError, ValueError):
                    args_dict = {}
                tool_calls.append(_make_tool_call(
                    tc_id=f"call_{i}_{name}",
                    name=name,
                    arguments_json=json.dumps(args_dict, ensure_ascii=False),
                ))

    if json_mode and content_text:
        content_text = _strip_json_fence(content_text)

    finish_reason = "tool_calls" if tool_calls else (
        "stop" if "STOP" in finish_reason_raw or finish_reason_raw == "" else
        "length" if "MAX_TOKENS" in finish_reason_raw else "stop"
    )

    usage_meta = getattr(resp, "usage_metadata", None)
    prompt_tokens = getattr(usage_meta, "prompt_token_count", 0) if usage_meta else 0
    cached = getattr(usage_meta, "cached_content_token_count", 0) if usage_meta else 0
    completion_tokens = getattr(usage_meta, "candidates_token_count", 0) if usage_meta else 0

    return _make_response(
        content=content_text,
        tool_calls=tool_calls or None,
        finish_reason=finish_reason,
        prompt_tokens=prompt_tokens or 0,
        cached_tokens=cached or 0,
        completion_tokens=completion_tokens or 0,
    )


def _call_gemini(
    raw_client,
    model: str,
    messages: list,
    temperature: float = 1.0,
    max_tokens: int = 1024,
    tools: list | None = None,
    tool_choice: str | dict | None = None,
    response_format: dict | None = None,
) -> SimpleNamespace:
    from google.genai import types as gt  # lazy

    system, contents = _openai_messages_to_gemini(messages)
    json_mode = (response_format or {}).get("type") == "json_object"

    cfg_kwargs: dict[str, Any] = {
        "temperature": temperature,
        "max_output_tokens": max_tokens,
    }
    if system:
        cfg_kwargs["system_instruction"] = system
    if json_mode:
        cfg_kwargs["response_mime_type"] = "application/json"
    if tools:
        cfg_kwargs["tools"] = _openai_tools_to_gemini(tools)
        if tool_choice == "required":
            cfg_kwargs["tool_config"] = gt.ToolConfig(
                function_calling_config=gt.FunctionCallingConfig(mode="ANY")
            )
        elif isinstance(tool_choice, dict):
            fn = tool_choice.get("function") or {}
            if fn.get("name"):
                cfg_kwargs["tool_config"] = gt.ToolConfig(
                    function_calling_config=gt.FunctionCallingConfig(
                        mode="ANY", allowed_function_names=[fn["name"]]
                    )
                )
        # tool_choice == "auto" ist Gemini-Default

    cfg = gt.GenerateContentConfig(**cfg_kwargs)
    resp = raw_client.models.generate_content(model=model, contents=contents, config=cfg)
    return _gemini_response_to_openai(resp, json_mode=json_mode)


# ─────────────────────────────────────────────────────────────────────────────
# Haupt-Client
# ─────────────────────────────────────────────────────────────────────────────
class LLMClient:
    """Provider-agnostischer LLM-Client mit OpenAI-kompatibler Schnittstelle.

    Nutzung:
        client = LLMClient("anthropic", api_key="sk-ant-...")
        response = client.chat.completions.create(
            model="claude-haiku-4-5",
            messages=[...],
            temperature=0.2,
            max_tokens=1100,
            response_format={"type": "json_object"},
        )
        text = response.choices[0].message.content
    """

    SUPPORTED_PROVIDERS = ("openai", "anthropic", "gemini", "deepseek", "deepinfra")

    def __init__(self, provider: str, api_key: str, timeout: float = 120.0):
        provider = (provider or "").lower().strip()
        if provider not in self.SUPPORTED_PROVIDERS:
            raise ValueError(
                f"Unbekannter LLM-Provider '{provider}'. "
                f"Erlaubt: {self.SUPPORTED_PROVIDERS}"
            )
        if not api_key:
            raise ValueError(f"Kein API-Key fuer Provider '{provider}' gesetzt.")

        self.provider = provider
        self.api_key = api_key
        self.timeout = timeout
        self._raw = self._init_raw()
        self.chat = _ChatAPI(self)

    def _init_raw(self):
        """Instanziiert den unterliegenden SDK-Client. Lazy Import."""
        if self.provider == "openai":
            from openai import OpenAI
            return OpenAI(api_key=self.api_key, timeout=self.timeout)
        if self.provider == "deepseek":
            from openai import OpenAI
            return OpenAI(
                api_key=self.api_key,
                base_url="https://api.deepseek.com",
                timeout=self.timeout,
            )
        if self.provider == "deepinfra":
            # DeepInfra hostet dasselbe DeepSeek-Modell (FP8) hinter einem
            # OpenAI-kompatiblen Endpunkt — kein eigener Adapter noetig.
            # Cache-Hits meldet DeepInfra im OpenAI-Feld
            # usage.prompt_tokens_details.cached_tokens, die Telemetrie
            # greift also unveraendert.
            from openai import OpenAI
            return OpenAI(
                api_key=self.api_key,
                base_url="https://api.deepinfra.com/v1/openai",
                timeout=self.timeout,
            )
        if self.provider == "anthropic":
            try:
                from anthropic import Anthropic
            except ImportError as e:
                raise ImportError(
                    "Anthropic-SDK nicht installiert. Bitte `pip install anthropic` "
                    "oder requirements.txt installieren."
                ) from e
            return Anthropic(api_key=self.api_key, timeout=self.timeout)
        if self.provider == "gemini":
            try:
                from google import genai
            except ImportError as e:
                raise ImportError(
                    "Google-Genai-SDK nicht installiert. Bitte `pip install google-genai` "
                    "oder requirements.txt installieren."
                ) from e
            return genai.Client(api_key=self.api_key)
        raise ValueError(f"Unbekannter Provider: {self.provider}")

    # Passthrough fuer OpenAI-spezifische Features (Batch-API: files + batches).
    # Nur fuer provider == "openai" zugelassen. Aufrufer MUSS vor Nutzung pruefen.
    @property
    def files(self):
        if self.provider != "openai":
            raise NotImplementedError(
                f"files-API nur fuer OpenAI verfuegbar, nicht fuer '{self.provider}'."
            )
        return self._raw.files

    @property
    def batches(self):
        if self.provider != "openai":
            raise NotImplementedError(
                f"batches-API nur fuer OpenAI verfuegbar, nicht fuer '{self.provider}'."
            )
        return self._raw.batches


class _ChatAPI:
    def __init__(self, parent: LLMClient):
        self.completions = _CompletionsAPI(parent)


class _CompletionsAPI:
    def __init__(self, parent: LLMClient):
        self._parent = parent

    def create(
        self,
        model: str,
        messages: list,
        temperature: float = 1.0,
        max_tokens: int = 1024,
        tools: list | None = None,
        tool_choice: Any = None,
        response_format: dict | None = None,
        **extra,
    ):
        p = self._parent.provider
        if p in ("openai", "deepseek", "deepinfra"):
            # OpenAI-, DeepSeek- und DeepInfra-API sind schemakompatibel (beide
            # dispatchen ueber den OpenAI-SDK mit base_url-Override).
            # Parameter 1:1, None-Werte weglassen.
            kwargs: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            if tools is not None:
                kwargs["tools"] = tools
            if tool_choice is not None:
                kwargs["tool_choice"] = tool_choice
            if response_format is not None:
                kwargs["response_format"] = response_format
            kwargs.update(extra)
            return self._parent._raw.chat.completions.create(**kwargs)

        if p == "anthropic":
            return _call_anthropic(
                self._parent._raw, model=model, messages=messages,
                temperature=temperature, max_tokens=max_tokens,
                tools=tools, tool_choice=tool_choice,
                response_format=response_format,
            )

        if p == "gemini":
            return _call_gemini(
                self._parent._raw, model=model, messages=messages,
                temperature=temperature, max_tokens=max_tokens,
                tools=tools, tool_choice=tool_choice,
                response_format=response_format,
            )

        raise ValueError(f"Unbekannter Provider: {p}")


# ─────────────────────────────────────────────────────────────────────────────
# Factory + Utilities
# ─────────────────────────────────────────────────────────────────────────────
def build_client(provider: str, api_key: str, timeout: float = 120.0) -> LLMClient | None:
    """Baut einen LLMClient, gibt None bei fehlendem Key zurueck (statt Exception)."""
    if not api_key:
        logger.warning(
            "Kein API-Key fuer Provider '%s' gesetzt — Client deaktiviert.", provider
        )
        return None
    try:
        return LLMClient(provider=provider, api_key=api_key, timeout=timeout)
    except ImportError as e:
        logger.error("Provider '%s' SDK-Import fehlgeschlagen: %s", provider, e)
        return None
    except Exception as e:
        logger.error("Provider '%s' Init fehlgeschlagen: %s", provider, e)
        return None
