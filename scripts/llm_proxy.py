"""Logging reverse proxy in front of Ollama: one record per model call, same for every harness.

Records start/first-byte/end times (epoch seconds), token counts reported by
the server, and the number of tool calls the model requested.
"""
import http.client
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def parse_call(body, stream):
    """Extract usage and tool-call count from a response body; unknown stays None."""
    usage, tools = None, 0
    chunks = ([line[5:].strip() for line in body.decode(errors='replace').splitlines() if line.startswith('data:')]
              if stream else [body.decode(errors='replace')])
    seen = set()
    for chunk in chunks:
        try:
            event = json.loads(chunk)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        if isinstance(event.get('usage'), dict):
            usage = event['usage']
        for choice in event.get('choices') or []:
            part = choice.get('delta') or choice.get('message') or {}
            for call in part.get('tool_calls') or []:
                key = call.get('id') or call.get('index')
                if stream and key is not None:
                    seen.add(key)
                else:
                    tools += 1
    return usage, tools + len(seen)


class Proxy:
    """Start with Proxy(port).start(); call .log_to(path) before each trial."""

    def __init__(self, port, upstream=('127.0.0.1', 11434), host='127.0.0.1'):
        self.lock = threading.Lock()
        self.path = None
        proxy = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def log_message(self, *args):
                pass

            def handle_any(self):
                started = time.time()
                if 'chunked' in (self.headers.get('Transfer-Encoding') or '').lower():
                    # Some clients stream the request body in chunks and send no Content-Length.
                    payload = b''
                    while True:
                        size = int(self.rfile.readline().split(b';')[0].strip() or b'0', 16)
                        if size == 0:
                            while self.rfile.readline().strip():
                                pass
                            break
                        payload += self.rfile.read(size)
                        self.rfile.readline()
                    del self.headers['Transfer-Encoding']
                    self.headers['Content-Length'] = str(len(payload))
                else:
                    length = int(self.headers.get('Content-Length') or 0)
                    payload = self.rfile.read(length) if length else None
                stream = False
                try:
                    body = json.loads(payload) if payload else {}
                    stream = bool(body.get('stream'))
                    if stream and 'chat/completions' in self.path and 'stream_options' not in body:
                        # Standard OpenAI option: Ollama then reports token usage in the last chunk.
                        body['stream_options'] = {'include_usage': True}
                        payload = json.dumps(body).encode()
                        del self.headers['Content-Length']
                        self.headers['Content-Length'] = str(len(payload))
                except (ValueError, AttributeError):
                    pass
                upstream_conn = http.client.HTTPConnection(*upstream, timeout=3600)
                headers = {k: v for k, v in self.headers.items() if k.lower() not in ('host', 'connection')}
                status, first, captured = 502, None, bytearray()
                try:
                    upstream_conn.request(self.command, self.path, payload, headers)
                    response = upstream_conn.getresponse()
                    status = response.status
                    self.send_response(status)
                    for key, value in response.getheaders():
                        if key.lower() not in ('transfer-encoding', 'connection', 'content-length'):
                            self.send_header(key, value)
                    self.send_header('Transfer-Encoding', 'chunked')
                    self.end_headers()
                    while True:
                        data = response.read1(65536)
                        if not data:
                            break
                        if first is None:
                            first = time.time()
                        captured += data
                        self.wfile.write(f'{len(data):X}\r\n'.encode() + data + b'\r\n')
                        self.wfile.flush()
                    self.wfile.write(b'0\r\n\r\n')
                except (OSError, http.client.HTTPException):
                    if first is None:
                        try:
                            self.send_error(502)
                        except OSError:
                            pass
                finally:
                    upstream_conn.close()
                    if self.path.endswith('/chat/completions') or self.path.endswith('/completions'):
                        usage, tools = parse_call(bytes(captured), stream)
                        proxy.record({'start': started, 'first_byte': first, 'end': time.time(),
                                      'status': status, 'stream': stream, 'tool_calls': tools,
                                      'input_tokens': (usage or {}).get('prompt_tokens'),
                                      'output_tokens': (usage or {}).get('completion_tokens')})

            do_GET = do_POST = handle_any

        self.server = ThreadingHTTPServer((host, port), Handler)
        self.server.daemon_threads = True

    def log_to(self, path):
        with self.lock:
            self.path = path

    def record(self, entry):
        with self.lock:
            if self.path:
                with open(self.path, 'a') as log:
                    log.write(json.dumps(entry) + '\n')

    def start(self):
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


def summarize_calls(path, agent_started):
    """Per-trial metrics from a calls file; None when no file was written."""
    try:
        calls = [json.loads(line) for line in open(path) if line.strip()]
    except (OSError, ValueError):
        return None
    import statistics
    ok = [c for c in calls if c.get('status') == 200]
    latencies = [c['end'] - c['start'] for c in ok]
    ttfts = [c['first_byte'] - c['start'] for c in ok if c.get('first_byte')]
    def tokens(key):
        known = [c[key] for c in ok if isinstance(c.get(key), int)]
        return sum(known) if known else None
    complete = bool(ok) and all(isinstance(c.get('input_tokens'), int) and isinstance(c.get('output_tokens'), int) for c in ok)
    return {
        'llm_calls': len(calls),
        'tool_calls': sum(c.get('tool_calls', 0) for c in ok),
        'first_call_seconds': (min(c['start'] for c in calls) - agent_started) if calls and agent_started else None,
        'call_latency_median': statistics.median(latencies) if latencies else None,
        'ttft_median': statistics.median(ttfts) if ttfts else None,
        'llm_seconds': sum(latencies) if latencies else None,
        'proxy_usage_complete': complete,
        'proxy_input_tokens': tokens('input_tokens'),
        'proxy_output_tokens': tokens('output_tokens'),
    }
