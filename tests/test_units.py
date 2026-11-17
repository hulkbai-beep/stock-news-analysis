"""Unit tests for parsing, time handling, de-duplication and key hygiene. Standard library only:

    python -m unittest discover -s tests
"""
import datetime as dt
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["SNA_OFFLINE"] = "1"
os.environ["SNA_DATA_DIR"] = tempfile.mkdtemp(prefix="sna-test-")

from sna import fixtures, netio, news, textutil, timeutil  # noqa: E402
from sna.sources import cftc, fred, rss, sec  # noqa: E402

UTC = dt.timezone.utc


class TimeTests(unittest.TestCase):
    def test_formats(self):
        want = dt.datetime(2026, 10, 7, 18, 0, tzinfo=UTC)
        self.assertEqual(timeutil.parse_time("Wed, 7 Oct 2026 18:00:00 GMT"), want)        # Fed: day not padded
        self.assertEqual(timeutil.parse_time("Wed, 07 Oct 2026 14:00:00 -0400"), want)     # Seeking Alpha style
        self.assertEqual(timeutil.parse_time("2026-10-07T18:00:00Z"), want)                 # Massive
        self.assertEqual(timeutil.parse_time("2026-10-07T18:00:00.000"), want)              # CFTC (naive = UTC)
        self.assertEqual(timeutil.parse_time(int(want.timestamp())), want)                  # 华尔街见闻, Finnhub
        self.assertEqual(timeutil.parse_time(str(int(want.timestamp()) * 1000)), want)      # milliseconds
        self.assertEqual(timeutil.parse_time("20261007T180000Z"), want)                     # GDELT
        self.assertEqual(timeutil.parse_time("2026-10-07 14:00:00", "ET"), want)            # FMP news (EDT)
        self.assertEqual(timeutil.parse_time("2026-11-06 08:30:00", "ET"),
                         dt.datetime(2026, 11, 6, 13, 30, tzinfo=UTC))                     # after DST ended
        self.assertIsNone(timeutil.parse_time("not a date"))

    def test_eastern_offset(self):
        hours = lambda *a: timeutil.et_offset(dt.datetime(*a, tzinfo=UTC)).total_seconds() / 3600
        self.assertEqual(hours(2026, 3, 8, 6, 59), -5)
        self.assertEqual(hours(2026, 3, 8, 7, 0), -4)
        self.assertEqual(hours(2026, 11, 1, 5, 59), -4)
        self.assertEqual(hours(2026, 11, 1, 6, 0), -5)

    def test_13f_deadline(self):
        self.assertEqual(timeutil.next_13f_deadline(dt.date(2026, 11, 7)),
                         (dt.date(2026, 9, 30), dt.date(2026, 11, 16)))   # Nov 14 is a Saturday
        self.assertEqual(timeutil.next_13f_deadline(dt.date(2026, 11, 17))[0], dt.date(2026, 12, 31))


class TextTests(unittest.TestCase):
    def test_canonical_url(self):
        a = textutil.canonical_url("https://www.example.com/story/x/?mod=mw_rss_topstories&utm_source=a")
        self.assertEqual(a, "example.com/story/x")
        self.assertEqual(textutil.canonical_url("http://example.com/a?id=7&utm_medium=b"), "example.com/a?id=7")

    def test_strip_html_and_links(self):
        self.assertEqual(textutil.strip_html("<p>A&nbsp;&amp; B</p>\n<script>x()</script>"), "A & B")
        self.assertIsNone(textutil.safe_url("javascript:alert(1)"))
        self.assertEqual(textutil.safe_url(" https://a.example/x "), "https://a.example/x")


class ParserTests(unittest.TestCase):
    def test_rss_with_namespaces_and_bad_entities(self):
        body = fixtures._file("seekingalpha.xml")
        items = rss.parse_feed(body)
        self.assertEqual(len(items), 4)
        self.assertEqual(items[0]["tickers"], ["DEMO"])
        self.assertEqual(items[0]["author"], "Sample Analyst")
        broken = b"<rss><channel><item><title>A &nbsp; B</title><link>https://x.example/a</link></item></channel></rss>"
        self.assertEqual(rss.parse_feed(broken)[0]["link"], "https://x.example/a")

    def test_atom(self):
        body = (b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>T</title>'
                b'<link rel="alternate" href="https://x.example/t"/><updated>2026-11-06T10:00:00Z</updated></entry></feed>')
        entry = rss.parse_feed(body)[0]
        self.assertEqual((entry["title"], entry["link"]), ("T", "https://x.example/t"))

    def test_form4(self):
        doc = sec.parse_form4(fixtures._file("sec/form4_a.xml"))
        self.assertTrue(doc["plan_10b5_1"])
        self.assertEqual(doc["owners"][0]["roles"], ["Chief Financial Officer"])
        self.assertEqual([t["code"] for t in doc["transactions"]], ["S", "S", "S"])
        self.assertAlmostEqual(doc["transactions"][0]["value"], 4200 * 157.10, places=2)
        footnote_only = sec.parse_form4(fixtures._file("sec/form4_d.xml"))
        self.assertTrue(footnote_only["plan_10b5_1"])          # no aff10b5One element, plan named in a footnote
        self.assertFalse(sec.parse_form4(fixtures._file("sec/form4_b.xml"))["plan_10b5_1"])

    def test_fred_csv_both_headers(self):
        old = "DATE,DGS10\n2026-11-04,4.10\n2026-11-05,.\n2026-11-06,4.13\n"
        new = "observation_date,DGS10\n2026-11-04,4.10\n2026-11-05,\n2026-11-06,4.13\n"
        for text in (old, new):
            self.assertEqual(fred.parse_csv(text), [("2026-11-04", 4.10), ("2026-11-06", 4.13)])

    def test_cot_summary(self):
        rows = [{"report_date_as_yyyy_mm_dd": f"2026-{m:02d}-01T00:00:00.000", "open_interest_all": "1000",
                 "asset_mgr_positions_long": str(500 + m), "asset_mgr_positions_short": "100",
                 "lev_money_positions_long": "100", "lev_money_positions_short": str(300 + m),
                 "dealer_positions_long_all": "50", "dealer_positions_short_all": "60"} for m in range(12, 0, -1)]
        s = cftc.summarize({"code": "X", "label": "x"}, rows)
        self.assertEqual(s["asset_mgr"]["net"], 412)
        self.assertEqual(s["asset_mgr"]["change_1w"], 1)
        self.assertEqual(s["asset_mgr"]["pctile_3y"], 100)
        self.assertEqual(s["lev_money"]["pctile_3y"], 8)        # the most short of the 12 weeks

    def test_13dg_filer_names(self):
        page = fixtures._file("sec/0009999901-26-000089-index.htm").decode()
        names = sec._COMPANY.findall(page)
        self.assertEqual(names[1], ("EXAMPLE CAPITAL ADVISORS &amp; CO", "Filed by"))


class DedupeTests(unittest.TestCase):
    def item(self, source, title, url, hours, sentiment=None):
        return {"source": source, "source_label": source, "publisher": source, "title": title, "url": url,
                "published_utc": timeutil.iso(dt.datetime(2026, 11, 6, 12, tzinfo=UTC) - dt.timedelta(hours=hours)),
                "summary": "", "tickers": ["DEMO"], "sentiment": sentiment, "lang": "en", "kind": "news"}

    def test_merge_by_url_and_title(self):
        rows = news.dedupe([
            self.item("fmp", "Demo Robotics raises its outlook", "https://example.com/a?utm_source=x", 1),
            self.item("massive", "Demo Robotics Raises Its Outlook", "https://www.example.com/a", 1.2,
                      {"label": "positive"}),
            self.item("alpaca", "Demo Robotics Stock Jumps: Here's What Investors Need To Know", "https://b.example/1", 2),
            self.item("gdelt", "Demo Robotics stock jumps: here's what investors need to know", "https://c.example/2", 3),
            self.item("nasdaq", "Demo Robotics stock jumps: here's what investors need to know", "https://d.example/3", 90),
            self.item("finnhub", "Demo Robotics adds a board member", "https://e.example/4", 4),
        ])
        self.assertEqual(len(rows), 4)
        first = next(r for r in rows if r["source"] == "massive")
        self.assertEqual([a["source"] for a in first["also"]], ["fmp"])
        self.assertEqual(first["sentiment"], {"label": "positive"})
        jumps = next(r for r in rows if r["source"] == "alpaca")
        self.assertEqual([a["source"] for a in jumps["also"]], ["gdelt"])   # the 90-hour-old copy stays apart


class KeyHygieneTests(unittest.TestCase):
    def test_redact_and_scrub(self):
        url = netio.build_url("https://x.example/q", {"symbol": "A", "apikey": "sekret-123456"})
        self.assertNotIn("sekret", netio.redact(url, ("apikey",)))
        os.environ["FMP_API_KEY"] = "sekret-123456"
        try:
            self.assertEqual(netio.scrub("failed for sekret-123456"), "failed for ***")
        finally:
            del os.environ["FMP_API_KEY"]


if __name__ == "__main__":
    unittest.main()
