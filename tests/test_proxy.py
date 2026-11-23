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


def test_output_check_and_sign_test(tmp_path):
    import subprocess, sys
    sys.path.insert(0, 'scripts')
    from adapters.command import OUTPUT_CHECK
    from campaign_results import sign_test
    prompt = tmp_path / 'prompt.txt'
    prompt.write_text('Write answer.json. Write analyze.py.')
    run = lambda: subprocess.run([sys.executable, '-c', OUTPUT_CHECK, str(tmp_path), str(prompt)],
                                 capture_output=True, text=True).stdout
    assert 'answer.json does not exist' in run() and 'analyze.py does not exist' in run()
    (tmp_path / 'answer.json').write_text('{"a": 1}\n}')
    (tmp_path / 'analyze.py').write_text('')
    assert 'not valid JSON' in run()
    (tmp_path / 'answer.json').write_text('{"a": 1}')
    assert run().strip() == ''
    assert sign_test(0, 0) is None and sign_test(5, 0) == 0.0625 and sign_test(2, 2) == 1.0


def test_busy_upstream_is_retried_before_any_reply_byte(tmp_path):
    seen = []

    class Busy(Fake):
        def do_POST(self):
            seen.append(1)
            if len(seen) == 1:
                self.rfile.read(int(self.headers["Content-Length"]))
                self.send_response(503); self.send_header("Content-Length", "0"); self.end_headers()
                self.close_connection = True
                return
            super().do_POST()

    upstream = HTTPServer(("127.0.0.1", 0), Busy)
    threading.Thread(target=upstream.serve_forever, daemon=True).start()
    proxy = Proxy(0, upstream=("127.0.0.1", upstream.server_port), retries=2).start()
    log = tmp_path / "calls.jsonl"
    proxy.log_to(log)
    assert b"usage" in post(proxy.server.server_port, False)
    time.sleep(0.2)
    proxy.stop(); upstream.shutdown()
    call = json.loads(log.read_text())
    assert (len(seen), call["status"], call["retries"]) == (2, 200, 1)


def test_remote_provider_gets_its_key_and_rewritten_path_not_the_clients(tmp_path):
    seen = {}

    class Remote(Fake):
        def do_POST(self):
            seen.update(path=self.path, auth=self.headers.get("Authorization"), encoding=self.headers.get("Accept-Encoding"))
            super().do_POST()

    upstream = HTTPServer(("127.0.0.1", 0), Remote)
    threading.Thread(target=upstream.serve_forever, daemon=True).start()

    class Plain(http.client.HTTPConnection):  # the test upstream speaks plain HTTP on a local port
        def __init__(self, host, timeout=None):
            super().__init__("127.0.0.1", upstream.server_port, timeout=timeout)

    original = http.client.HTTPSConnection
    http.client.HTTPSConnection = Plain
    try:
        proxy = Proxy(0, remote=dict(host="provider.test", key="secret", path_from="/v1", path_to="/v1beta/openai", min_interval=0)).start()
        proxy.log_to(tmp_path / "calls.jsonl")
        conn = http.client.HTTPConnection("127.0.0.1", proxy.server.server_port)
        conn.request("POST", "/v1/chat/completions", json.dumps({"stream": False}),
                     {"Content-Type": "application/json", "Authorization": "Bearer dummy", "Accept-Encoding": "gzip"})
        assert b"usage" in conn.getresponse().read()
    finally:
        http.client.HTTPSConnection = original
        proxy.stop(); upstream.shutdown()
    assert seen == {"path": "/v1beta/openai/chat/completions", "auth": "Bearer secret", "encoding": "identity"}
