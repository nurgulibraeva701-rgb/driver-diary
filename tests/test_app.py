import json, os, tempfile, threading, unittest, urllib.request, urllib.error
from http.server import ThreadingHTTPServer
from app.core import Store, ValidationError, Conflict, summarize, validate
from app.server import make_handler

def trip(**kw):
    t = {"id": "a", "start": "2026-10-01T08:00:00+05:00", "end": "2026-10-01T08:30:00+05:00",
         "amount": 1000, "payment": "card", "commission": 150}
    t.update(kw); return t

class Summary(unittest.TestCase):
    def test_empty(self):
        s = summarize([])
        self.assertEqual((s["trips"], s["revenue"], s["net"]), (0, 0, 0))
    def test_totals_and_split(self):
        s = summarize([trip(id="1", amount=2400, commission=360),
                       trip(id="2", amount=1500, commission=225, payment="cash")])
        self.assertEqual(s["trips"], 2); self.assertEqual(s["revenue"], 3900)
        self.assertEqual(s["commission"], 585); self.assertEqual(s["net"], 3315)
        self.assertEqual(s["cash"], {"trips": 1, "amount": 1500})
        self.assertEqual(s["card"], {"trips": 1, "amount": 2400})
    def test_float_rounding(self):
        self.assertEqual(summarize([trip(amount=0.1), trip(amount=0.2, commission=0)])["revenue"], 0.3)

class Validation(unittest.TestCase):
    def test_bad(self):
        for bad in (trip(amount=0), trip(amount=-5), trip(amount="10"), trip(amount=True),
                    trip(end="2026-10-01T08:00:00+05:00"), trip(end="2026-10-01T07:00:00+05:00"),
                    trip(payment="bitcoin"), trip(commission=2000), trip(id=""),
                    trip(start="2026-10-01T08:00:00")):
            with self.assertRaises(ValidationError, msg=bad): validate(bad)

class Normalize(unittest.TestCase):
    def test_time_format_is_normalized(self):
        t = validate(trip(start="2026-10-01 08:00+05:00", end="2026-10-01 08:30+05:00"))
        self.assertEqual((t["start"], t["end"]), ("2026-10-01T08:00:00+05:00", "2026-10-01T08:30:00+05:00"))

class Dedup(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "t.json"); self.s = Store(self.path)
    def test_repeat_is_idempotent(self):
        _, c1 = self.s.add(trip()); _, c2 = self.s.add(trip())
        self.assertTrue(c1); self.assertFalse(c2)
        self.assertEqual(len(self.s.list("2026-10-01")), 1)
        self.assertEqual(len(json.load(open(self.path))), 1)
    def test_same_id_other_data_conflicts(self):
        self.s.add(trip())
        with self.assertRaises(Conflict): self.s.add(trip(amount=999))
    def test_survives_restart(self):
        self.s.add(trip()); self.assertFalse(Store(self.path).add(trip())[1])

class Http(unittest.TestCase):
    def test_flow(self):
        store = Store(os.path.join(tempfile.mkdtemp(), "t.json"))
        srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(store))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{srv.server_port}"
        def post(b):
            r = urllib.request.Request(base + "/api/trips", json.dumps(b).encode(), {"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(r) as x: return x.status, json.load(x)
            except urllib.error.HTTPError as e: return e.code, json.load(e)
        self.assertEqual(post(trip())[0], 201)
        self.assertEqual(post(trip())[0], 200)
        self.assertEqual(post(trip(id="b", amount=0))[0], 422)
        self.assertEqual(post(trip(amount=999))[0], 409)
        with urllib.request.urlopen(base + "/api/trips?date=2026-10-01") as x: j = json.load(x)
        self.assertEqual(j["summary"]["trips"], 1); srv.shutdown()

if __name__ == "__main__": unittest.main()
