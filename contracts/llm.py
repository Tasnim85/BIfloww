"""Shared LLM client. Every agent that uses an LLM goes through here, so EVERY call
is written to the audit journal (provider, model, prompt version, hashes).

Rules for the whole team:
  * the LLM never computes a number or takes a decision: Python/SQL do that;
  * outputs are STRUCTURED (JSON validated by a Pydantic class);
  * temperature 0 + fixed seed, so a call can be replayed;
  * prompts are versioned like rules: prompt_version="prompt:<name>@<version>".

Providers (choose with BIFLOW_LLM_PROVIDER, default "groq"):
  groq        free API, no credit card      key: GROQ_API_KEY    (console.groq.com)
  gemini      free API (Google AI Studio)   key: GEMINI_API_KEY  (aistudio.google.com)
  openrouter  free models                   key: OPENROUTER_API_KEY
  ollama      local, no key                 needs Ollama + a pulled model
Override the model with BIFLOW_LLM_MODEL. Keys go in a `.env` file at the repo root
(NEVER committed: `.env` is in .gitignore), e.g.  GROQ_API_KEY=gsk_...
"""
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, Field, ValidationError

from contracts.common import Contract

M = TypeVar("M", bound=BaseModel)

PRESETS = {   # provider -> (base_url, default model, env var holding the key)
    "groq": ("https://api.groq.com/openai/v1", "llama-3.3-70b-versatile", "GROQ_API_KEY"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai", "gemini-2.5-flash",
               "GEMINI_API_KEY"),
    "openrouter": ("https://openrouter.ai/api/v1", "meta-llama/llama-3.3-70b-instruct:free",
                   "OPENROUTER_API_KEY"),
    "ollama": ("http://localhost:11434", "qwen2.5:7b", None),
}


def _load_dotenv(path: Path = Path(".env")) -> None:
    """Minimal .env reader (KEY=value lines). Real environment variables win."""
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()


def _default(i: int):
    provider = os.environ.get("BIFLOW_LLM_PROVIDER", "groq")
    return PRESETS.get(provider, PRESETS["groq"])[i]


class LLMConfig(Contract):
    provider: str = Field(default_factory=lambda: os.environ.get("BIFLOW_LLM_PROVIDER", "groq"))
    model: str = Field(default_factory=lambda: os.environ.get("BIFLOW_LLM_MODEL") or _default(1))
    base_url: str = Field(default_factory=lambda: os.environ.get("BIFLOW_LLM_BASE_URL") or _default(0))
    temperature: float = 0.0
    seed: int = 42
    timeout_s: float = 120.0

    def api_key(self) -> str | None:
        env = PRESETS.get(self.provider, (None, None, None))[2]
        return os.environ.get(env) if env else None


class LLMUnavailable(RuntimeError):
    """No server, no key, rate limit... Callers fall back to their templates.
    `detail` keeps the provider's full error body (it can hold a recoverable answer)."""

    def __init__(self, message: str, detail: str = ""):
        super().__init__(message)
        self.detail = detail


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


MAX_RATE_WAIT_S = 20.0     # wait for a free-tier rate limit at most this long, twice


def _rate_wait(e: urllib.error.HTTPError, detail: str) -> float | None:
    """Seconds the provider asks us to wait (Retry-After header or 'try again in 5.9s')."""
    header = e.headers.get("retry-after") if e.headers else None
    if header:
        try:
            return float(header)
        except ValueError:
            pass
    m = re.search(r"try again in ([\d.]+)s", detail)
    return float(m.group(1)) if m else None


def _post(url: str, payload: dict, timeout: float, headers: dict | None = None) -> dict:
    """HTTP call, isolated so tests can replace it. Waits and retries on a short rate limit."""
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={
        "Content-Type": "application/json", "User-Agent": "biflow/1.0", **(headers or {})})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            wait = _rate_wait(e, detail) if e.code == 429 else None
            if wait is not None and wait <= MAX_RATE_WAIT_S and attempt < 2:
                time.sleep(wait + 0.5)
                continue
            _raise_http(e, detail)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            raise LLMUnavailable(f"LLM server not reachable at {url}: {e}") from e


def _raise_http(e: urllib.error.HTTPError, detail: str):
    reason = {401: "invalid API key", 403: "access refused", 429: "rate limit reached"}.get(e.code, "")
    raise LLMUnavailable(f"HTTP {e.code} {reason}: {detail[:300]}", detail=detail) from e


# Provider errors where the model's output is retried or recovered instead of giving up
JSON_MODE_FAILED = ("json_validate_failed", "output_parse_failed")


def _extract_json(text: str) -> str:
    """The JSON object inside a free-text answer (code fences or prose around it)."""
    start, end = text.find("{"), text.rfind("}")
    return text[start:end + 1] if start != -1 and end > start else text


def list_models(config: LLMConfig | None = None) -> list[str]:
    """Model ids this key can use (OpenAI-compatible providers only)."""
    config = config or LLMConfig()
    if config.provider == "ollama":
        url, pick = f"{config.base_url}/api/tags", lambda r: [m["name"] for m in r.get("models", [])]
        headers = {}
    else:
        url, pick = f"{config.base_url}/models", lambda r: [m["id"] for m in r.get("data", [])]
        headers = {"Authorization": f"Bearer {config.api_key()}"}
    req = urllib.request.Request(url, headers={"User-Agent": "biflow/1.0", **headers})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return sorted(pick(json.loads(r.read().decode("utf-8"))))
    except Exception as e:
        raise LLMUnavailable(f"Cannot list models at {url}: {e}") from e


def _ask(config: LLMConfig, messages: list[dict], schema: type[BaseModel]) -> str:
    """One request, returns the raw JSON text of the answer."""
    if config.provider == "ollama":
        raw = _post(f"{config.base_url}/api/chat", {
            "model": config.model, "messages": messages, "stream": False,
            "format": schema.model_json_schema(),
            "options": {"temperature": config.temperature, "seed": config.seed}}, config.timeout_s)
        return raw.get("message", {}).get("content", "")

    key = config.api_key()
    if not key:
        env = PRESETS.get(config.provider, (None, None, "?"))[2]
        raise LLMUnavailable(f"No API key: set {env} in .env (provider '{config.provider}')")
    body = {"model": config.model, "messages": messages,
            "temperature": config.temperature, "seed": config.seed,
            "response_format": {"type": "json_object"}}
    headers = {"Authorization": f"Bearer {key}"}
    try:
        try:
            raw = _post(f"{config.base_url}/chat/completions", body, config.timeout_s, headers)
        except LLMUnavailable as e:
            # Some models (e.g. gpt-oss on Groq) fail the provider's JSON mode
            # ("json_validate_failed"): ask again without it and extract the JSON ourselves.
            if not any(code in e.detail or code in str(e) for code in JSON_MODE_FAILED):
                raise
            body.pop("response_format")
            raw = _post(f"{config.base_url}/chat/completions", body, config.timeout_s, headers)
            return _extract_json(raw["choices"][0]["message"]["content"] or "")
    except LLMUnavailable as e:
        if "model_not_found" in str(e) or "does not exist" in str(e):
            try:
                available = ", ".join(list_models(config))
            except LLMUnavailable:
                available = "(could not list them)"
            raise LLMUnavailable(f"Model '{config.model}' is not available for this key. "
                                 f"Available: {available}. Set BIFLOW_LLM_MODEL=<one of them> in .env") from e
        raise
    return raw["choices"][0]["message"]["content"] or ""


def chat_json(system: str, user: str, schema: type[M], *, prompt_version: str,
              ctx=None, step: str = "llm_call", config: LLMConfig | None = None,
              history: list[dict] | None = None) -> M:
    """Ask for a JSON answer that must validate against `schema` (one retry if it does not).

    ctx: the agent's RunContext. If given, the call is logged in the audit journal.
    history: earlier turns of a multi-step conversation ({"role", "content"} dicts),
    placed between the system prompt and `user` (used by tool-using agents).
    Raises LLMUnavailable (no server/key, rate limit) or ValidationError (bad answer twice).
    """
    config = config or LLMConfig()
    system_full = (f"{system}\n\nAnswer ONLY with a JSON object that validates against this "
                   f"JSON Schema:\n{json.dumps(schema.model_json_schema())}")
    messages = ([{"role": "system", "content": system_full}] + list(history or [])
                + [{"role": "user", "content": user}])
    sent = json.dumps(messages, ensure_ascii=False)          # what was sent first (hashed)
    t0, content, attempts, decision = time.perf_counter(), "", 0, "answered"
    try:
        for attempts in (1, 2):
            content = _ask(config, messages, schema)
            try:
                return schema.model_validate_json(content)
            except ValidationError as e:
                if attempts == 2:
                    raise
                messages += [{"role": "assistant", "content": content},
                             {"role": "user", "content": f"Invalid JSON for the schema: {e}. "
                                                         f"Answer again with valid JSON only."}]
    except Exception as e:
        decision = f"error: {type(e).__name__}"
        raise
    finally:
        if ctx is not None:
            ctx.log(f"llm:{step}", decision, rule_version=prompt_version, evidence={
                "provider": config.provider, "model": config.model,
                "temperature": config.temperature, "seed": config.seed, "attempts": attempts,
                "prompt_sha256": _sha(sent),
                "output_sha256": _sha(content) if content else None,
                "duration_s": round(time.perf_counter() - t0, 2)})


# ---- native tool calling (agents that use tools) ------------------------------------
class ToolCall(BaseModel):
    name: str
    args: dict = Field(default_factory=dict)
    id: str = ""                  # provider's call id ("" = answered in plain text)


def _args(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}


def _recover_call(detail: str) -> ToolCall | None:
    """Groq 'tool_use_failed': the model made a valid call the API refused. Keep it."""
    try:
        failed = json.loads(json.loads(detail)["error"]["failed_generation"])
        return ToolCall(name=str(failed["name"]).split("<|")[0].strip(),
                        args=_args(failed.get("arguments")), id="recovered")
    except Exception:
        return None


def _assistant_message(call: ToolCall, content: str = "", ollama: bool = False) -> dict:
    if not call.id:
        return {"role": "assistant", "content": content}
    args = call.args if ollama else json.dumps(call.args, ensure_ascii=False)   # Ollama wants a dict
    return {"role": "assistant", "content": content, "tool_calls": [{
        "id": call.id, "type": "function", "function": {"name": call.name, "arguments": args}}]}


def tool_message(call: ToolCall, content: str) -> dict:
    """The message that gives a tool's result back to the model."""
    if not call.id:
        return {"role": "user", "content": content}
    return {"role": "tool", "tool_call_id": call.id, "content": content}


def chat_tools(messages: list[dict], tools: list[dict], *, prompt_version: str, ctx=None,
               step: str = "llm_tools", config: LLMConfig | None = None,
               final_tool: str = "final_answer", force_tool: str | None = None) -> tuple[ToolCall, dict]:
    """One turn of a tool-using agent, with the provider's NATIVE tool calling.

    tools: function specs [{"name", "description", "parameters": JSON Schema}].
    Returns (the call the model made, the assistant message to append to `messages`).
    A plain-text answer becomes a call to `final_tool` with {"answer": text}.
    force_tool: oblige the model to call that tool now (e.g. final_answer on the last turn).
    Recovers a call the provider refused ("tool_use_failed") and retries an
    unparsable output once. Logged in the journal like chat_json.
    """
    config = config or LLMConfig()
    sent = json.dumps(messages, ensure_ascii=False)
    t0, decision, call = time.perf_counter(), "answered", None
    try:
        for attempt in (1, 2):
            try:
                call, content = _ask_tools(config, messages, tools, force_tool)
                break
            except LLMUnavailable as e:
                recovered = _recover_call(e.detail) if "tool_use_failed" in e.detail else None
                if recovered:
                    call, content, decision = recovered, "", "answered (call recovered)"
                    break
                retryable = any(code in e.detail for code in JSON_MODE_FAILED) or "tool_use_failed" in e.detail
                if attempt == 1 and retryable:
                    continue                                   # unusable output: try once more
                raise
        if not call.id and call.name != final_tool:
            call = ToolCall(name=final_tool, args={"answer": content})
        return call, _assistant_message(call, content, ollama=config.provider == "ollama")
    except Exception as e:
        decision = f"error: {type(e).__name__}"
        raise
    finally:
        if ctx is not None:
            ctx.log(f"llm:{step}", decision, rule_version=prompt_version, evidence={
                "provider": config.provider, "model": config.model, "temperature": config.temperature,
                "tool_called": call.name if call else None, "prompt_sha256": _sha(sent),
                "duration_s": round(time.perf_counter() - t0, 2)})


def _ask_tools(config: LLMConfig, messages: list[dict], tools: list[dict],
               force_tool: str | None = None) -> tuple[ToolCall, str]:
    specs = [{"type": "function", "function": t} for t in tools]
    if config.provider == "ollama":
        raw = _post(f"{config.base_url}/api/chat", {
            "model": config.model, "messages": messages, "tools": specs, "stream": False,
            "options": {"temperature": config.temperature, "seed": config.seed}}, config.timeout_s)
        msg = raw.get("message", {})
    else:
        key = config.api_key()
        if not key:
            env = PRESETS.get(config.provider, (None, None, "?"))[2]
            raise LLMUnavailable(f"No API key: set {env} in .env (provider '{config.provider}')")
        raw = _post(f"{config.base_url}/chat/completions", {
            # "auto", not "required": gpt-oss often writes its final answer as plain text,
            # which "required" makes the provider reject; plain text becomes final_answer.
            "model": config.model, "messages": messages, "tools": specs,
            "tool_choice": {"type": "function", "function": {"name": force_tool}} if force_tool else "auto",
            "temperature": config.temperature, "seed": config.seed}, config.timeout_s,
            {"Authorization": f"Bearer {key}"})
        msg = raw["choices"][0]["message"]
    calls = msg.get("tool_calls") or []
    content = msg.get("content") or ""
    if not calls:
        return ToolCall(name="", args={}), content
    first = calls[0]
    fn = first.get("function", {})
    name = fn.get("name", "").split("<|")[0].strip()      # gpt-oss: "search_journal<|channel|>commentary"
    return ToolCall(name=name, args=_args(fn.get("arguments")),
                    id=first.get("id") or "call_0"), content


def ping(config: LLMConfig | None = None) -> str:
    """Quick end-to-end test of the configured provider. Returns the model's answer."""
    class Pong(BaseModel):
        answer: str
    config = config or LLMConfig()
    return chat_json("You are a test.", 'Reply with {"answer": "pong"}.', Pong,
                     prompt_version="prompt:ping@1.0", config=config).answer


if __name__ == "__main__":      # python -m contracts.llm   |   python -m contracts.llm --models
    import sys
    cfg = LLMConfig()
    print(f"provider={cfg.provider} model={cfg.model} base_url={cfg.base_url}")
    try:
        if "--models" in sys.argv:
            print("Models available for this key:")
            for m in list_models(cfg):
                print("  ", m)
        else:
            print("answer:", ping(cfg))
    except LLMUnavailable as e:
        print("LLM unavailable:", e)
        sys.exit(1)
