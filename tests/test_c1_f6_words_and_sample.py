"""Cycle 1, F6: plain words in rendered pages, and the sample data walk-through."""
from html.parser import HTMLParser

from conftest import local_client

BANNED = ("anchor", "criteri", "deal-breaker", "dealbreaker", "weight")


def _visible_text(html: str) -> str:
    class P(HTMLParser):
        def __init__(self):
            super().__init__()
            self.out, self.skip = [], 0

        def handle_starttag(self, tag, attrs):
            if tag in ("script", "style"):
                self.skip += 1
            for k, v in attrs:
                if k in ("placeholder", "title", "aria-label", "alt") and v:
                    self.out.append(v)

        def handle_endtag(self, tag):
            if tag in ("script", "style") and self.skip:
                self.skip -= 1

        def handle_data(self, data):
            if not self.skip:
                self.out.append(data)
    p = P()
    p.feed(html)
    return " ".join(p.out).lower()


def _check(html: str, label: str):
    text = _visible_text(html)
    for word in BANNED:
        assert word not in text, (label, word, text[max(0, text.index(word) - 60): text.index(word) + 60])


def test_no_jargon_in_main_pages(sample_store):
    s = sample_store
    c = local_client(s)
    places = s.list_places(s.current_search()["id"])
    ids = ",".join(str(p["id"]) for p in places[:3])
    paths = ["/today", "/board", "/board?show_hidden=1", f"/compare?ids={ids}", "/map", "/calendar", "/search", "/add",
             "/import", "/checklist", "/settings", "/contacts", "/connect", "/privacy", "/ai", "/backups"]
    paths += [f"/places/{p['id']}" for p in places]
    for path in paths:
        r = c.get(path)
        assert r.status_code == 200, path
        _check(r.text, path)
    _check(c.post("/add/parse", data={"text": "Elm\n$900/mo 1 bed"}).text, "/add/parse")


def test_sample_data_pages_work_and_scam_is_not_a_best_fit(sample_store):
    from prophelper import enrich, today

    s = sample_store
    c = local_client(s)
    search = s.current_search()
    rows = enrich.enrich_places(s, search)
    scam = [p for p in rows if p["title"] == "Bright Lakeview Condo"][0]
    assert today.possible_scam(scam)
    assert scam["title"] not in [p["title"] for p in today.best_fits(rows)]
    html = c.get("/today").text
    best = html.split("Best fits", 1)[1].split("</section>", 1)[0] if "Best fits" in html else ""
    assert "Bright Lakeview Condo" not in best
    assert "Check first" in c.get("/board").text
