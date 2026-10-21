"""The shared LLM client, tested against a fake local server (no key, no model needed).
Covers both wire formats: Ollama's /api/chat and the OpenAI-compatible /chat/completions
(used by Groq, Gemini, OpenRouter)."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from pydantic import BaseModel, ValidationError

from contracts.audit import read_events
from contracts.llm import LLMConfig, LLMUnavailable, chat_json, chat_tools, tool_message
from contracts.pipeline import context_for


class Answer(BaseModel):
    summary: str


class FakeServer(BaseHTTPRequestHandler):
    requests: list = []
    replies: list = []          # contents to return, in order

    def do_GET(self):                       # /models
        body = {"data": [{"id": "openai/gpt-oss-120b"}, {"id": "llama-3.1-8b-instant"}]}
        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeServer.requests.append({"path": self.path, "payload": payload,
                                    "auth": self.headers.get("Authorization")})
        content = FakeServer.replies.pop(0)
        if content == "400T":                 # Groq refused a valid native tool call
            self.send_response(400)
            self.end_headers()
            gen = json.dumps({"name": "trace_lineage", "arguments": {"node": "list"}})
            self.wfile.write(json.dumps({"error": {"code": "tool_use_failed",
                                                   "failed_generation": gen}}).encode())
            return
        if content == "400E":                 # tool_use_failed with nothing to recover
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b'{"error":{"code":"tool_use_failed","failed_generation":""}}')
            return
        if content == "400P":                 # model wrote unparsable text
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b'{"error":{"code":"output_parse_failed","failed_generation":"We need"}}')
            return
        if content == "429":                  # free-tier rate limit, retry immediately
            self.send_response(429)
            self.send_header("Retry-After", "0")
            self.end_headers()
            self.wfile.write(b'{"error":{"message":"Rate limit reached. Please try again in 0s."}}')
            return
        if content == "400J":                 # Groq: model output failed JSON mode
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b'{"error":{"code":"json_validate_failed","failed_generation":""}}')
            return
        if content == "404":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'{"error":{"code":"model_not_found","message":"does not exist"}}')
            return
        message = content if isinstance(content, dict) else {"role": "assistant", "content": content}
        if self.path.endswith("/api/chat"):
            body = {"message": message}
        else:
            body = {"choices": [{"message": message}]}
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    FakeServer.requests, FakeServer.replies = [], []
    srv = HTTPServer(("127.0.0.1", 0), FakeServer)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def ok(text="ok 941,291.36") -> str:
    return json.dumps({"summary": text})


def test_groq_style_call_is_sent_and_journaled(server, tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    FakeServer.replies = [ok()]
    ctx = context_for("comparisons", "test", runs_root=tmp_path, journal=tmp_path / "j.db")
    cfg = LLMConfig(provider="groq", base_url=server, model="llama-3.3-70b-versatile")
    out = chat_json("system", "user", Answer, prompt_version="prompt:test@1.0", ctx=ctx, config=cfg)
    assert out.summary == "ok 941,291.36"

    sent = FakeServer.requests[0]
    assert sent["path"] == "/chat/completions" and sent["auth"] == "Bearer gsk_test"
    assert sent["payload"]["response_format"] == {"type": "json_object"}
    assert sent["payload"]["temperature"] == 0.0 and sent["payload"]["seed"] == 42
    assert "JSON Schema" in sent["payload"]["messages"][0]["content"]

    event = read_events(tmp_path / "j.db")[-1]
    assert (event.step, event.decision, event.rule_version) == ("llm:llm_call", "answered", "prompt:test@1.0")
    assert event.evidence["provider"] == "groq" and len(event.evidence["prompt_sha256"]) == 64


def test_ollama_style_call(server):
    FakeServer.replies = [ok()]
    cfg = LLMConfig(provider="ollama", base_url=server, model="qwen2.5:7b")
    assert chat_json("s", "u", Answer, prompt_version="p@1", config=cfg).summary == "ok 941,291.36"
    assert FakeServer.requests[0]["payload"]["format"] == Answer.model_json_schema()


def test_invalid_json_is_retried_once(server, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    FakeServer.replies = ["not json", ok("second try")]
    cfg = LLMConfig(provider="groq", base_url=server)
    assert chat_json("s", "u", Answer, prompt_version="p@1", config=cfg).summary == "second try"
    assert len(FakeServer.requests) == 2


def test_invalid_json_twice_raises(server, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    FakeServer.replies = ["nope", "still nope"]
    with pytest.raises(ValidationError):
        chat_json("s", "u", Answer, prompt_version="p@1", config=LLMConfig(provider="groq", base_url=server))


def test_unknown_model_lists_available_ones(server, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    FakeServer.replies = ["404"]
    with pytest.raises(LLMUnavailable, match="Available: llama-3.1-8b-instant, openai/gpt-oss-120b"):
        chat_json("s", "u", Answer, prompt_version="p@1",
                  config=LLMConfig(provider="groq", base_url=server, model="gone-model"))


def test_missing_key_means_unavailable(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(LLMUnavailable, match="GROQ_API_KEY"):
        chat_json("s", "u", Answer, prompt_version="p@1", config=LLMConfig(provider="groq"))


def test_no_server_means_unavailable():
    with pytest.raises(LLMUnavailable):
        chat_json("s", "u", Answer, prompt_version="p@1",
                  config=LLMConfig(provider="ollama", base_url="http://127.0.0.1:9", timeout_s=2))


def test_provider_json_mode_failure_falls_back_to_plain_mode(server, monkeypatch):
    """gpt-oss on Groq sometimes fails JSON mode (HTTP 400 json_validate_failed)."""
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    FakeServer.replies = ["400J", 'Sure! ```json\n{"summary": "plain mode"}\n```']
    out = chat_json("s", "u", Answer, prompt_version="p@1", config=LLMConfig(provider="groq", base_url=server))
    assert out.summary == "plain mode"
    assert "response_format" in FakeServer.requests[0]["payload"]
    assert "response_format" not in FakeServer.requests[1]["payload"]


def test_short_rate_limit_is_waited_out(server, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    FakeServer.replies = ["429", ok("after the wait")]
    out = chat_json("s", "u", Answer, prompt_version="p@1", config=LLMConfig(provider="groq", base_url=server))
    assert out.summary == "after the wait" and len(FakeServer.requests) == 2


# ---- native tool calling ---------------------------------------------------------------
TOOLS = [{"name": "trace_lineage", "description": "d",
          "parameters": {"type": "object", "properties": {"node": {"type": "string"}}}}]
CALL = {"role": "assistant", "content": "", "tool_calls": [
    {"id": "call_1", "type": "function",
     "function": {"name": "trace_lineage", "arguments": "{\"node\": \"list\"}"}}]}


def test_native_tool_call(server, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    FakeServer.replies = [CALL]
    call, assistant = chat_tools([{"role": "user", "content": "q"}], TOOLS, prompt_version="p@1",
                                 config=LLMConfig(provider="groq", base_url=server))
    assert (call.name, call.args, call.id) == ("trace_lineage", {"node": "list"}, "call_1")
    sent = FakeServer.requests[0]["payload"]
    assert sent["tools"][0]["function"]["name"] == "trace_lineage" and sent["tool_choice"] == "auto"
    assert assistant["tool_calls"][0]["id"] == "call_1"
    assert tool_message(call, "result") == {"role": "tool", "tool_call_id": "call_1", "content": "result"}


def test_refused_tool_call_is_recovered(server, monkeypatch):
    """Groq 'Tool choice is none, but model called a tool': the call itself was fine."""
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    FakeServer.replies = ["400T"]
    call, _ = chat_tools([{"role": "user", "content": "q"}], TOOLS, prompt_version="p@1",
                         config=LLMConfig(provider="groq", base_url=server))
    assert (call.name, call.args) == ("trace_lineage", {"node": "list"})


def test_unparsable_output_is_retried(server, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    FakeServer.replies = ["400P", CALL]
    call, _ = chat_tools([{"role": "user", "content": "q"}], TOOLS, prompt_version="p@1",
                         config=LLMConfig(provider="groq", base_url=server))
    assert call.name == "trace_lineage" and len(FakeServer.requests) == 2


def test_plain_text_becomes_final_answer(server, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    FakeServer.replies = [{"role": "assistant", "content": "Je ne sais pas."}]
    call, _ = chat_tools([{"role": "user", "content": "q"}], TOOLS, prompt_version="p@1",
                         config=LLMConfig(provider="groq", base_url=server))
    assert (call.name, call.args) == ("final_answer", {"answer": "Je ne sais pas."})


def test_empty_tool_failure_is_retried(server, monkeypatch):
    """'Tool choice is required, but model did not call a tool' (nothing to recover)."""
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    FakeServer.replies = ["400E", {"role": "assistant", "content": "Réponse finale."}]
    call, _ = chat_tools([{"role": "user", "content": "q"}], TOOLS, prompt_version="p@1",
                         config=LLMConfig(provider="groq", base_url=server))
    assert (call.name, call.args) == ("final_answer", {"answer": "Réponse finale."})


def test_force_tool_is_sent(server, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    FakeServer.replies = [CALL]
    chat_tools([{"role": "user", "content": "q"}], TOOLS, prompt_version="p@1", force_tool="trace_lineage",
               config=LLMConfig(provider="groq", base_url=server))
    assert FakeServer.requests[0]["payload"]["tool_choice"] == {"type": "function",
                                                               "function": {"name": "trace_lineage"}}


def test_channel_tokens_are_removed_from_tool_names(server, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    leaky = {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "type": "function",
             "function": {"name": "search_journal<|channel|>commentary", "arguments": "{}"}}]}
    FakeServer.replies = [leaky]
    call, _ = chat_tools([{"role": "user", "content": "q"}], TOOLS, prompt_version="p@1",
                         config=LLMConfig(provider="groq", base_url=server))
    assert call.name == "search_journal"
