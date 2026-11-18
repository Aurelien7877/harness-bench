"""Proxy records calls, tokens and tool calls without a model, Docker or Ollama."""
import http.client
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from scripts.llm_proxy import Proxy, summarize_calls


class Fake(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream" if body["stream"] else "application/json")
        self.end_headers()
        usage = {"prompt_tokens": 7, "completion_tokens": 3}
        if body["stream"]:
            for event in ({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1"}]}}]},
                          {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1"}]}}]},
                          {"choices": [], "usage": usage}):
                self.wfile.write(b"data: " + json.dumps(event).encode() + b"\n\n")
            self.wfile.write(b"data: [DONE]\n\n")
        else:
            self.wfile.write(json.dumps({"choices": [{"message": {"tool_calls": [{}, {}]}}], "usage": usage}).encode())
        self.close_connection = True


def post(port, stream):
    conn = http.client.HTTPConnection("127.0.0.1", port)
    conn.request("POST", "/v1/chat/completions", json.dumps({"stream": stream}), {"Content-Type": "application/json"})
    return conn.getresponse().read()


@pytest.mark.parametrize("stream,tools", [(False, 2), (True, 1)])
def test_proxy_logs_tokens_tool_calls_and_first_call(tmp_path, stream, tools):
    upstream = HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=upstream.serve_forever, daemon=True).start()
    proxy = Proxy(0, upstream=("127.0.0.1", upstream.server_port))
    port = proxy.server.server_port
    proxy.start()
    log = tmp_path / "calls.jsonl"
    proxy.log_to(log)
    started = time.time() - 5
    assert b"usage" in post(port, stream)
    time.sleep(0.2)
    proxy.stop(); upstream.shutdown()
    metrics = summarize_calls(log, started)
    assert (metrics["llm_calls"], metrics["tool_calls"]) == (1, tools)
    assert (metrics["proxy_input_tokens"], metrics["proxy_output_tokens"]) == (7, 3)
    assert metrics["first_call_seconds"] >= 5 and metrics["ttft_median"] >= 0


def test_missing_call_log_is_unknown(tmp_path):
    assert summarize_calls(tmp_path / "none.jsonl", 0) is None


def test_chunked_request_body_is_forwarded_and_measured(tmp_path):
    upstream = HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=upstream.serve_forever, daemon=True).start()
    proxy = Proxy(0, upstream=("127.0.0.1", upstream.server_port))
    proxy.start()
    log = tmp_path / "calls.jsonl"
    proxy.log_to(log)
    conn = http.client.HTTPConnection("127.0.0.1", proxy.server.server_port)
    conn.request("POST", "/v1/chat/completions", iter([b'{"stream":', b' true}']),
                 {"Content-Type": "application/json"}, encode_chunked=True)
    assert b"usage" in conn.getresponse().read()
    time.sleep(0.2)
    proxy.stop(); upstream.shutdown()
    metrics = summarize_calls(log, 0)
    assert (metrics["llm_calls"], metrics["tool_calls"], metrics["proxy_input_tokens"]) == (1, 1, 7)
