import json, os, sys
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from .core import Store, ValidationError, Conflict, summarize

STATIC = os.path.join(os.path.dirname(__file__), "..", "static")


def make_handler(store):
    class H(BaseHTTPRequestHandler):
        def _send(self, code, body, ctype="application/json; charset=utf-8"):
            data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _day(self, q):
            d = (q.get("date") or [""])[0]
            try:
                date.fromisoformat(d)
            except ValueError:
                self._send(400, {"error": "параметр date=YYYY-MM-DD обязателен"})
                return None
            return d

        def do_GET(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if u.path in ("/", "/index.html"):
                with open(os.path.join(STATIC, "index.html"), "rb") as f:
                    return self._send(200, f.read(), "text/html; charset=utf-8")
            if u.path == "/api/days":
                return self._send(200, {"days": store.days()})
            if u.path in ("/api/trips", "/api/summary"):
                d = self._day(q)
                if d is None:
                    return
                trips = store.list(d)
                if u.path == "/api/summary":
                    return self._send(200, {"date": d, "summary": summarize(trips)})
                return self._send(200, {"date": d, "trips": trips, "summary": summarize(trips)})
            self._send(404, {"error": "не найдено"})

        def do_POST(self):
            if urlparse(self.path).path != "/api/trips":
                return self._send(404, {"error": "не найдено"})
            try:
                n = int(self.headers.get("Content-Length", 0))
                raw = json.loads(self.rfile.read(n) or b"null")
                trip, created = store.add(raw)
            except json.JSONDecodeError:
                return self._send(400, {"error": "некорректный JSON"})
            except ValidationError as e:
                return self._send(422, {"error": str(e)})
            except Conflict as e:
                return self._send(409, {"error": str(e)})
            self._send(201 if created else 200, {"trip": trip, "created": created})

        def log_message(self, *a):
            pass

    return H


def main():
    path = os.environ.get("DATA_FILE", os.path.join(os.path.dirname(__file__), "..", "data", "trips.json"))
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    print(f"http://localhost:{port}")
    ThreadingHTTPServer(("", port), make_handler(Store(path))).serve_forever()


if __name__ == "__main__":
    main()
