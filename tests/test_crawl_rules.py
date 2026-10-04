from protego import Protego

from agent.scout.tools.crawl import USER_AGENT, feed_links, is_feed, same_site, sites_for, skipped


def test_same_site_rule():
    ietf = sites_for({"url": "https://www.ietf.org", "entry_urls": ["https://datatracker.ietf.org/doc/recent"]})
    assert ietf == {"ietf.org", "datatracker.ietf.org"}
    assert same_site("https://datatracker.ietf.org/doc/draft-x", ietf)
    assert same_site("https://www.ietf.org/blog/", ietf)
    assert not same_site("https://ietf.example.com/", ietf)
    cisco = sites_for({"url": "https://blogs.cisco.com"})
    assert same_site("https://blogs.cisco.com/news", cisco)
    assert not same_site("https://www.cisco.com/", cisco)


def test_skip_patterns_and_file_types():
    patterns = ["login", "/tag/"]
    assert skipped("https://a.com/login?next=/", patterns)
    assert skipped("https://a.com/files/report.PNG", patterns)
    assert not skipped("https://a.com/careers/quantum-team", patterns)   # careers is no longer skipped


def test_robots_wildcards_are_obeyed():
    rules = Protego.parse("User-agent: *\nDisallow: /*?*\n")
    assert not rules.can_fetch("https://inc42.com/buzz/x/?utm=1", USER_AGENT)
    assert rules.can_fetch("https://inc42.com/buzz/x/", USER_AGENT)


def test_feeds_are_recognised_and_read():
    rss = ('<?xml version="1.0"?><rss><channel><item><title>A</title>'
           "<link>https://a.com/1</link></item><item><link><![CDATA[https://a.com/2]]></link></item>"
           "</channel></rss>")
    atom = '<feed xmlns="http://www.w3.org/2005/Atom"><entry><link href="https://b.com/x"/></entry></feed>'
    assert is_feed("application/rss+xml", "") and is_feed("text/xml", rss) and is_feed("", atom)
    assert not is_feed("text/html", "<html><head><link rel=alternate type='application/rss+xml'>")
    assert feed_links(rss) == ["https://a.com/1", "https://a.com/2"]
    assert feed_links(atom) == ["https://b.com/x"]


def test_the_page_budget_comes_from_crawl_settings_and_a_runs_own_wins(db):
    from agent.scout.tools.collect import page_budget, recorded_snapshot
    from app.services.signals import snapshot

    db["settings"].insert_one({"_id": "crawl", "pages_per_source": 12})
    db["runs"].insert_one({"_id": "r", **snapshot.build()})  # what a run records at its start
    db["settings"].update_one({"_id": "crawl"}, {"$set": {"pages_per_source": 99}})  # edited mid-run
    assert page_budget(recorded_snapshot("r")) == 12          # the run keeps what it started with
    assert page_budget(recorded_snapshot("r"), override=5) == 5
    assert page_budget(snapshot.build()) == 99                # the next run gets the edit
