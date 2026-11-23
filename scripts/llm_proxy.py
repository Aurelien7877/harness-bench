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

    def __init__(self, port, upstream=('127.0.0.1', 11434), host='127.0.0.1', retries=0, remote=None):
        """remote = dict(host, key, path_from, path_to, min_interval): an HTTPS provider reached with the key kept here."""
        self.lock = threading.Lock()
        self.path = None
        self.next_start = 0.0
        remote = remote or {}
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
                    changed = False
                    for field in remote.get('drop_fields', ()):
                        # OpenAI-only options (for example `store`) that a stricter provider rejects with HTTP 400.
                        changed |= body.pop(field, None) is not None
                    if stream and 'chat/completions' in self.path and 'stream_options' not in body:
                        # Standard OpenAI option: the server then reports token usage in the last chunk.
                        body['stream_options'] = {'include_usage': True}
                        changed = True
                    if changed:
                        payload = json.dumps(body).encode()
                        del self.headers['Content-Length']
                        self.headers['Content-Length'] = str(len(payload))
                except (ValueError, AttributeError):
                    pass
                skipped = ('host', 'connection') + (('authorization', 'accept-encoding') if remote else ())
                headers = {k: v for k, v in self.headers.items() if k.lower() not in skipped}
                request_path = self.path
                if remote:
                    # The harness holds a dummy key; the real one is added here and never reaches a container.
                    headers['Authorization'] = 'Bearer ' + remote['key']
                    headers['Accept-Encoding'] = 'identity'
                    if request_path.startswith(remote['path_from']):
                        request_path = remote['path_to'] + request_path[len(remote['path_from']):]
                busy = (429, 500, 502, 503, 504) if remote else (429, 502, 503)
                status, first, captured, tries, upstream_conn, busy_notes = 502, None, bytearray(), 0, None, []
                try:
                    while True:
                        proxy.wait_turn(remote.get('min_interval', 0))
                        upstream_conn = (http.client.HTTPSConnection(remote['host'], timeout=600) if remote
                                         else http.client.HTTPConnection(*upstream, timeout=3600))
                        try:
                            upstream_conn.request(self.command, request_path, payload, headers)
                            response = upstream_conn.getresponse()
                        except (OSError, http.client.HTTPException):
                            upstream_conn.close()
                            if not remote or tries >= retries:
                                raise
                            tries += 1
                            time.sleep(min(30, 2 ** tries))
                            continue
                        if response.status in busy and tries < retries:
                            # A busy service answers before any byte of the model reply: wait and ask again.
                            wait = response.getheader('Retry-After')
                            busy_notes.append(f'{response.status}: ' + response.read()[:240].decode(errors='replace'))
                            upstream_conn.close()
                            tries += 1
                            time.sleep(min(60, float(wait)) if wait and wait.replace('.', '', 1).isdigit() else min(30, 2 ** tries))
                            continue
                        break
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
                    if upstream_conn:
                        upstream_conn.close()
                    if self.path.endswith('/completions'):
                        usage, tools = parse_call(bytes(captured), stream)
                        proxy.record({'start': started, 'first_byte': first, 'end': time.time(),
                                      'status': status, 'stream': stream, 'retries': tries, 'busy': busy_notes[-2:],
                                      'error': bytes(captured[:300]).decode(errors='replace') if status != 200 else None, 'tool_calls': tools,
                                      'input_tokens': (usage or {}).get('prompt_tokens'),
                                      'output_tokens': (usage or {}).get('completion_tokens')})

            do_GET = do_POST = handle_any

        class Server(ThreadingHTTPServer):
            def handle_error(self, request, client_address):
                pass  # clients closing keep-alive connections abruptly is normal, not an error

        self.server = Server((host, port), Handler)
        self.server.daemon_threads = True

    def wait_turn(self, interval):
        """Space request starts by `interval` seconds to stay under a requests-per-minute limit."""
        if not interval:
            return
        with self.lock:
            now = time.time()
            start = max(now, self.next_start)
            self.next_start = start + interval
        time.sleep(max(0, start - now))

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
