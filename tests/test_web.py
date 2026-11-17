"""The local server end to end on offline sample data: every endpoint answers, the host check holds, the API is
read-only and bad input is refused."""
import http.client
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["SNA_OFFLINE"] = "1"
os.environ["SNA_DATA_DIR"] = tempfile.mkdtemp(prefix="sna-web-")

from sna import web  # noqa: E402


class WebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = web.make_server(0)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def request(self, path, method="GET", host=None):
        con = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        con.request(method, path, headers={"Host": host or f"127.0.0.1:{self.port}"})
        resp = con.getresponse()
        body = resp.read()
        con.close()
        return resp.status, resp.getheader("Content-Type", ""), body

    def json(self, path):
        status, ctype, body = self.request(path)
        self.assertEqual(status, 200, body[:300])
        self.assertTrue(ctype.startswith("application/json"))
        return json.loads(body)

    def test_pages_and_static(self):
        for path in ("/", "/t/DEMO", "/status", "/static/app.js", "/static/app.css"):
            self.assertEqual(self.request(path)[0], 200, path)
        self.assertEqual(self.request("/static/../sna/config.py")[0], 404)

    def test_macro_endpoints(self):
        self.assertEqual(len(self.json("/api/macro/market")["sectors"]), 12)
        groups = self.json("/api/macro/fred")["groups"]
        self.assertTrue(all(r.get("found") for g in groups for r in g["rows"]))
        self.assertTrue(self.json("/api/macro/calendar")["events"])
        self.assertEqual(len(self.json("/api/macro/fed")["feeds"]), 2)
        self.assertTrue(all(m["found"] for m in self.json("/api/macro/cot")["markets"]))
        news = self.json("/api/macro/news")
        self.assertTrue(news["items"] and all(s["ok"] for s in news["sources"]))

    def test_ticker_endpoints(self):
        news = self.json("/api/ticker/demo/news?days=14")
        self.assertEqual(news["symbol"], "DEMO")
        self.assertLess(len(news["items"]), news["raw_count"])          # duplicates were merged
        self.assertTrue(any(i["sentiment"] for i in news["items"]))
        ins = self.json("/api/ticker/DEMO/insiders")
        self.assertEqual(ins["summary"]["buy"]["n"], 1)
        self.assertEqual(ins["summary"]["sell"]["n"], 4)
        filings = self.json("/api/ticker/DEMO/filings")
        self.assertEqual([h["form"] for h in filings["holders"]], ["SCHEDULE 13G/A", "SC 13D", "SC 13G"])
        self.assertEqual(filings["holders"][1]["filers"], ["SAMPLE ACTIVIST PARTNERS LP"])
        self.assertTrue(self.json("/api/ticker/DEMO/analysts")["grades"])
        self.assertEqual(self.json("/api/ticker/DEMO/overview")["name"], "Demo Robotics Inc.")

    def test_refusals(self):
        self.assertEqual(self.request("/api/status", host="evil.example")[0], 403)
        self.assertEqual(self.request("/api/ticker/BAD%20SYM/news")[0], 400)
        self.assertEqual(self.request("/api/ticker/DEMO/news?days=x")[0], 400)
        self.assertEqual(self.request("/api/macro/nothing")[0], 404)
        self.assertEqual(self.request("/api/status", method="POST")[0], 405)

    def test_status_never_returns_key_values(self):
        os.environ["FINNHUB_API_KEY"] = "sekret-abcdef"
        try:
            status, _, body = self.request("/api/status")
            self.assertEqual(status, 200)
            self.assertNotIn(b"sekret", body)
            self.assertTrue(json.loads(body)["keys"]["FINNHUB_API_KEY"])
        finally:
            del os.environ["FINNHUB_API_KEY"]


if __name__ == "__main__":
    unittest.main()
