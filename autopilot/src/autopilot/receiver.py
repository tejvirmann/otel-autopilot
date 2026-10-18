"""Minimal in-process OTLP/HTTP receiver that collects spans for verification."""
from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest


def _val(v):
    k = v.WhichOneof("value")
    return getattr(v, k) if k else None


class Span(dict):
    """Flat span record: name, kind, status, attrs, resource, events, trace_id, span_id, parent_id."""


class Collector:
    def __init__(self, port: int = 0):
        self.spans: list[Span] = []
        self.metric_requests = 0
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):  # quiet
                pass

            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("content-length", 0)))
                if self.path.endswith("/v1/traces"):
                    outer._ingest(body)
                elif self.path.endswith("/v1/metrics"):
                    outer.metric_requests += 1
                self.send_response(200)
                self.send_header("content-type", "application/x-protobuf")
                self.end_headers()

        self._srv = ThreadingHTTPServer(("127.0.0.1", port), H)
        self.port = self._srv.server_address[1]
        self._t = threading.Thread(target=self._srv.serve_forever, daemon=True)

    def start(self):
        self._t.start()
        return self

    def stop(self):
        self._srv.shutdown()

    def _ingest(self, body: bytes):
        req = ExportTraceServiceRequest()
        req.ParseFromString(body)
        for rs in req.resource_spans:
            res = {a.key: _val(a.value) for a in rs.resource.attributes}
            for ss in rs.scope_spans:
                for s in ss.spans:
                    self.spans.append(Span(
                        name=s.name, kind=s.kind, status=s.status.code,
                        attrs={a.key: _val(a.value) for a in s.attributes},
                        events=[{"name": e.name, "attrs": {a.key: _val(a.value) for a in e.attributes}} for e in s.events],
                        resource=res, trace_id=s.trace_id.hex(), span_id=s.span_id.hex(),
                        parent_id=s.parent_span_id.hex(), scope=ss.scope.name))
