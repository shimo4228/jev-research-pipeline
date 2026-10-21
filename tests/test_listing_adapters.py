"""Listing adapters (feed, sitemap) and the page they follow; the line's web search window.

Sources that publish no search — release notes, a team blog, a site's sitemap — are read as
listings: what is new inside a window before the run's date, each item's page fetched when the
listing carries no text (base.Follow)."""

import json
from datetime import date
from pathlib import Path

import httpx2
import pytest

from jev_research_pipeline.adapters import FetchOutcome, feed, page, sitemap, web_search
from jev_research_pipeline.jev.question_screening import no_abstract
from jev_research_pipeline.model import SourceItem
from jev_research_pipeline.pipeline import nets
from jev_research_pipeline.pipeline.config import load_tracks
from jev_research_pipeline.pipeline.run import make_adapter
from jev_research_pipeline.pipeline.units import split_units
from jev_research_pipeline.questions import parse_queries

from . import builders as b

TODAY = date(2026, 10, 20)
NO_ENV: dict[str, str] = {}
FEED_URL = "https://code.example.org/changelog/rss.xml"

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
<channel><title>Changelog</title>
<item><title>2.1.304</title><link>https://code.example.org/changelog#2-1-304</link>
<pubDate>Mon, 19 Oct 2026 21:50:26 GMT</pubDate>
<content:encoded><![CDATA[<p><strong>Added</strong></p><ul>
<li>Added <code>/auto-mode-setup</code>, a guided setup that reads your project</li>
<li>Added a warning when resuming would use a noticeable share of the usage limit</li>
</ul>]]></content:encoded></item>
<item><title>Team post</title><link>https://blog.example.org/team-post/</link>
<pubDate>Sun, 18 Oct 2026 12:00:00 GMT</pubDate>
<description>A short teaser the screen cannot judge.</description></item>
<item><title>Old release</title><link>https://code.example.org/changelog#2-1-290</link>
<pubDate>Mon, 05 Oct 2026 23:53:37 GMT</pubDate>
<content:encoded><![CDATA[<ul><li>Fixed something long ago, outside the window</li></ul>]]></content:encoded></item>
<item><title>Undated</title><link>https://code.example.org/undated</link>
<content:encoded><![CDATA[<p>No date, so the window cannot place it.</p>]]></content:encoded></item>
</channel></rss>"""

ATOM = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>Releases</title>
<entry><title>v2.1.304</title><link href="https://github.example.org/releases/v2.1.304"/>
<updated>2026-10-19T21:34:21Z</updated>
<content type="html">&lt;ul&gt;&lt;li&gt;Added review levels to Code Review&lt;/li&gt;&lt;/ul&gt;</content>
</entry></feed>"""

ARTICLE = """<html><head><title>How the team does code review</title></head><body>
<nav>Home Blog Docs</nav><main><h1>How the team does code review</h1>
<p>Once coverage was high, the team started optimizing for the minimum review a change needs.</p>
</main></body></html>"""

SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://www.example.org/engineering</loc><lastmod>2026-10-19T10:00:00.000Z</lastmod></url>
<url><loc>https://www.example.org/engineering/new-post</loc><lastmod>2026-10-19T13:19:29.000Z</lastmod></url>
<url><loc>https://www.example.org/engineering/old-post</loc><lastmod>2026-09-01T00:00:00.000Z</lastmod></url>
<url><loc>https://www.example.org/engineering-jobs/x</loc><lastmod>2026-10-19T00:00:00.000Z</lastmod></url>
<url><loc>https://www.example.org/legal/terms</loc><lastmod>2026-10-19T23:23:17.000Z</lastmod></url>
<url><loc>https://www.example.org/engineering/undated</loc></url>
</urlset>"""


def _client(
    pages: dict[str, httpx2.Response], asked: list[str] | None = None
) -> httpx2.AsyncClient:
    async def handle(request: httpx2.Request) -> httpx2.Response:
        url = str(request.url)
        if asked is not None:
            asked.append(url)
        return pages.get(url, httpx2.Response(404, text="not found"))

    return httpx2.AsyncClient(transport=httpx2.MockTransport(handle))


def _ok(outcome: FetchOutcome) -> tuple[SourceItem, ...]:
    assert outcome.failure is None, outcome.failure
    return outcome.sources


# --- feed ------------------------------------------------------------------------------


def test_feed_keeps_the_window_and_reads_full_content_as_lines():
    drafts = feed.parse(RSS, feed_url=FEED_URL, today=TODAY)
    assert [d["url"] for d in drafts] == [
        "https://code.example.org/changelog#2-1-304",
        "https://blog.example.org/team-post/",
    ]  # 2026-10-05 is before the window; the undated item is left out
    release, post = drafts
    assert release["published_at"] == date(2026, 10, 19)
    assert release["text"].split("\n") == [
        "Added",
        "Added /auto-mode-setup , a guided setup that reads your project",
        "Added a warning when resuming would use a noticeable share of the usage limit",
    ]
    assert post["text"] == ""  # a summary only: Follow fetches the page


def test_feed_window_counts_back_from_the_run_date():
    assert feed.WINDOW_DAYS == 3
    assert [d["title"] for d in feed.parse(RSS, feed_url=FEED_URL, today=date(2026, 10, 22))] == [
        "2.1.304"
    ]
    assert feed.parse(RSS, feed_url=FEED_URL, today=date(2026, 10, 23)) == []


def test_feed_reads_atom_entries():
    (entry,) = feed.parse(ATOM, feed_url="https://github.example.org/releases.atom", today=TODAY)
    assert entry["url"] == "https://github.example.org/releases/v2.1.304"
    assert entry["published_at"] == date(2026, 10, 19)
    assert entry["text"] == "Added review levels to Code Review"


def test_a_page_that_is_not_a_feed_is_a_parse_failure():
    with pytest.raises(ValueError, match="not an RSS or Atom feed"):
        feed.parse("<html><body>moved</body></html>", feed_url=FEED_URL, today=TODAY)


async def test_a_release_note_becomes_one_unit_per_bullet():
    client = _client({FEED_URL: httpx2.Response(200, text=RSS)})
    out = await feed.adapter(TODAY, FEED_URL).fetch(
        client, b.line(), FEED_URL, now=b.T0, env=NO_ENV
    )
    release = next(s for s in _ok(out) if s.title == "2.1.304")
    assert [u.text for u in split_units(release)] == [
        "Added /auto-mode-setup , a guided setup that reads your project",
        "Added a warning when resuming would use a noticeable share of the usage limit",
    ]


async def test_a_summary_only_item_is_judged_on_its_page():
    asked: list[str] = []
    client = _client(
        {
            FEED_URL: httpx2.Response(200, text=RSS),
            "https://blog.example.org/team-post/": httpx2.Response(200, text=ARTICLE),
        },
        asked,
    )
    out = await feed.adapter(TODAY, FEED_URL).fetch(
        client, b.line(), FEED_URL, now=b.T0, env=NO_ENV
    )
    post = next(s for s in _ok(out) if s.url == "https://blog.example.org/team-post/")
    assert post.title == "How the team does code review"
    assert "minimum review a change needs" in post.text
    assert "Home Blog Docs" not in post.text  # <main>, not the navigation
    assert post.published_at == date(2026, 10, 18)  # the feed's date, not the page's
    assert asked == [FEED_URL, "https://blog.example.org/team-post/"]  # full content: no fetch


async def test_a_page_that_cannot_be_fetched_is_skipped_and_counted():
    client = _client({FEED_URL: httpx2.Response(200, text=RSS)})  # the post's page is a 404
    out = await feed.adapter(TODAY, FEED_URL).fetch(
        client, b.line(), FEED_URL, now=b.T0, env=NO_ENV
    )
    assert [s.title for s in _ok(out)] == ["2.1.304"]
    assert out.skipped == 1  # the operations section names it (nets.VALIDATION_SKIPPED)


async def test_only_https_pages_are_followed_and_at_most_the_limit():
    items = "".join(
        f"<item><title>P{i}</title><link>{scheme}://blog.example.org/p{i}</link>"
        "<pubDate>Mon, 19 Oct 2026 12:00:00 GMT</pubDate><description>teaser</description></item>"
        for i, scheme in enumerate(["http", "https", "https"])
    )
    body = (
        f'<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>{items}</channel></rss>'
    )
    asked: list[str] = []
    pages = {f"https://blog.example.org/p{i}": httpx2.Response(200, text=ARTICLE) for i in (1, 2)}
    client = _client({FEED_URL: httpx2.Response(200, text=body), **pages}, asked)
    from dataclasses import replace

    adapter = feed.adapter(TODAY, FEED_URL)
    assert adapter.follow is not None
    limited = replace(adapter, follow=replace(adapter.follow, limit=1))
    out = await limited.fetch(client, b.line(), FEED_URL, now=b.T0, env=NO_ENV)
    assert [s.url for s in _ok(out)] == ["https://blog.example.org/p1"]
    assert (out.skipped, out.capped) == (1, 1)  # the http one is never asked for; p2 is past
    assert asked == [FEED_URL, "https://blog.example.org/p1"]  # the limit and said apart


def test_html_lines_puts_each_block_on_its_own_line():
    fragment = (
        "<h2>Fixed</h2><ul><li>Fixed a crash &amp; a hang</li><li></li></ul><p>Done.<br>Next</p>"
    )
    assert page.html_lines(fragment) == "Fixed\nFixed a crash & a hang\nDone.\nNext"


# --- sitemap ---------------------------------------------------------------------------


def test_sitemap_keeps_changed_pages_under_the_prefix():
    drafts = sitemap.parse(SITEMAP, prefix="https://www.example.org/engineering/", today=TODAY)
    assert [(d["url"], d["published_at"], d["text"]) for d in drafts] == [
        ("https://www.example.org/engineering/new-post", date(2026, 10, 19), "")
    ]  # not the listing page, a sibling path, an old post, another section or an undated one


def test_sitemap_pages_come_newest_first_whatever_the_sitemaps_order():
    """Follow's limit takes them in this order: a sitemap listed by name or id spent it on
    old pages and cut the new ones (2026-10-22)."""
    body = SITEMAP.replace(
        "</urlset>",
        "<url><loc>https://www.example.org/engineering/a-older</loc>"
        "<lastmod>2026-10-18T08:00:00.000Z</lastmod></url>"
        "<url><loc>https://www.example.org/engineering/z-newest</loc>"
        "<lastmod>2026-10-19T20:00:00.000Z</lastmod></url></urlset>",
    )
    drafts = sitemap.parse(body, prefix="https://www.example.org/engineering/", today=TODAY)
    assert [d["url"].rsplit("/", 1)[1] for d in drafts] == ["z-newest", "new-post", "a-older"]


def test_sitemap_prefix_without_its_trailing_slash_means_the_same():
    # authored_candidates strips edge punctuation, so the run sends the prefix without "/"
    drafts = sitemap.parse(SITEMAP, prefix="https://www.example.org/engineering", today=TODAY)
    assert [d["url"] for d in drafts] == ["https://www.example.org/engineering/new-post"]


def test_sitemap_is_asked_at_the_site_root():
    req = sitemap.build_request("https://www.example.org/engineering/", NO_ENV)
    assert str(req.url) == "https://www.example.org/sitemap.xml"


def test_a_sitemap_without_lastmod_yields_nothing():
    body = SITEMAP.replace("<lastmod>", "<x>").replace("</lastmod>", "</x>")
    assert sitemap.parse(body, prefix="https://www.example.org/engineering/", today=TODAY) == []


async def test_sitemap_pages_are_fetched_for_their_text():
    client = _client(
        {
            "https://www.example.org/sitemap.xml": httpx2.Response(200, text=SITEMAP),
            "https://www.example.org/engineering/new-post": httpx2.Response(200, text=ARTICLE),
        }
    )
    prefix = "https://www.example.org/engineering/"
    adapter = make_adapter("sitemap", today=TODAY, query=prefix)
    (post,) = _ok(await adapter.fetch(client, b.line(), prefix, now=b.T0, env=NO_ENV))
    assert post.adapter == "sitemap"
    assert post.title == "How the team does code review"
    assert post.published_at == date(2026, 10, 19)


# --- the line's web search window ------------------------------------------------------


def _body(request: httpx2.Request) -> dict[str, object]:
    return json.loads(request.content)


def test_web_search_without_a_window_sends_the_request_unchanged():
    body = _body(web_search.adapter().build_request("claude code hooks", NO_ENV))
    assert body == {
        "query": "claude code hooks",
        "max_results": 10,
        "search_depth": "basic",
        "topic": "general",
    }


def test_web_search_with_a_window_asks_for_dates_too():
    body = _body(web_search.adapter("week").build_request("claude code hooks", NO_ENV))
    assert body["time_range"] == "week"
    assert body["include_published_date"] is True


def _config(tmp_path: Path, track: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(f'[tracks.cc]\nname = "Claude Code"\n{track}\n', encoding="utf-8")
    return path


def test_web_time_range_is_read_per_line(tmp_path: Path):
    line = nets.for_line(_config(tmp_path, 'web_time_range = "week"'), "cc", nets.NetConfig())
    assert line.web_time_range == "week"
    other = nets.for_line(_config(tmp_path, ""), "cc", nets.NetConfig())
    assert other.web_time_range is None
    web = make_adapter("web_search", today=TODAY, web_time_range=line.web_time_range)
    assert _body(web.build_request("q x", NO_ENV))["time_range"] == "week"


def test_an_unknown_web_time_range_stops_where_the_config_loads(tmp_path: Path):
    path = _config(tmp_path, 'web_time_range = "fortnight"')
    with pytest.raises(ValueError, match="web_time_range"):
        load_tracks(path)  # jrp doctor's config check fails; no line runs
    assert nets.for_line(path, "cc", nets.NetConfig()).web_time_range is None


# --- question file ---------------------------------------------------------------------


def test_feed_and_sitemap_lines_are_query_lines():
    text = f"""<!-- jrp:questions:cc -->

## 公式の変更
- slug: official
- feed: {FEED_URL}
- sitemap: https://www.example.org/engineering/
"""
    assert parse_queries(text) == {
        "official": (("feed", FEED_URL), ("sitemap", "https://www.example.org/engineering/"))
    }


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Fri, 16 Oct 2026 17:00:00 GMT", date(2026, 10, 16)),  # what Tavily sends
        ("2026-10-16T17:00:00Z", date(2026, 10, 16)),
        ("sometime last week", None),
        ("Fri, 16 Oct 2026 17:00:00 +99999999999999999999999", None),  # OverflowError
        (None, None),
    ],
)
def test_web_search_reads_tavilys_published_dates(value: str | None, expected: date | None):
    assert web_search.published(value) == expected


async def test_a_redirect_on_the_same_host_is_followed_once_and_stored_where_it_landed():
    """anthropic.com/engineering/<slug> answers 308 to /research/<slug> (2026-10-21): a moved
    post is read, under the URL that served it."""
    client = _client(
        {
            FEED_URL: httpx2.Response(200, text=RSS),
            "https://blog.example.org/team-post/": httpx2.Response(
                308, text="Redirecting", headers={"location": "/research/team-post"}
            ),
            "https://blog.example.org/research/team-post": httpx2.Response(200, text=ARTICLE),
        }
    )
    out = await feed.adapter(TODAY, FEED_URL).fetch(
        client, b.line(), FEED_URL, now=b.T0, env=NO_ENV
    )
    moved = next(s for s in _ok(out) if s.title == "How the team does code review")
    assert moved.url == "https://blog.example.org/research/team-post"
    assert out.skipped == 0


@pytest.mark.parametrize(
    "location",
    [
        "https://elsewhere.example.net/team-post",  # another host
        "http://blog.example.org/team-post",  # off https
        "https://127.0.0.1/team-post",  # an address
        "/",  # the site's root: the post is gone, not moved
        "/login?next=/team-post/",  # a sign-in page
        "https://[blog.example.org/team-post",  # not a URL: no page, never a failed line
        "",  # no Location
    ],
)
async def test_a_redirect_off_the_pages_host_or_https_is_not_followed(location: str):
    asked: list[str] = []
    headers = {"location": location} if location else {}
    client = _client(
        {
            FEED_URL: httpx2.Response(200, text=RSS),
            "https://blog.example.org/team-post/": httpx2.Response(
                307, text="Redirecting", headers=headers
            ),
            location or "x": httpx2.Response(200, text=ARTICLE),
        },
        asked,
    )
    out = await feed.adapter(TODAY, FEED_URL).fetch(
        client, b.line(), FEED_URL, now=b.T0, env=NO_ENV
    )
    assert [s.title for s in _ok(out)] == ["2.1.304"]
    assert out.skipped == 1
    assert asked == [FEED_URL, "https://blog.example.org/team-post/"]


async def test_a_redirect_is_followed_at_most_once():
    client = _client(
        {
            FEED_URL: httpx2.Response(200, text=RSS),
            "https://blog.example.org/team-post/": httpx2.Response(301, headers={"location": "/a"}),
            "https://blog.example.org/a": httpx2.Response(301, headers={"location": "/b"}),
            "https://blog.example.org/b": httpx2.Response(200, text=ARTICLE),
        }
    )
    out = await feed.adapter(TODAY, FEED_URL).fetch(
        client, b.line(), FEED_URL, now=b.T0, env=NO_ENV
    )
    assert [s.title for s in _ok(out)] == ["2.1.304"] and out.skipped == 1


YOUTUBE_FEED = "https://www.youtube.com/feeds/videos.xml?channel_id=UCchannel"
YOUTUBE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015" xmlns:media="http://search.yahoo.com/mrss/" xmlns="http://www.w3.org/2005/Atom">
<title>Claude</title>
<entry><id>yt:video:v1</id><yt:videoId>v1</yt:videoId><yt:channelId>UCchannel</yt:channelId>
<title>Introducing Claude Duet</title>
<link rel="alternate" href="https://www.youtube.com/watch?v=v1"/>
<published>2026-10-19T16:00:00+00:00</published>
<media:group><media:title>Introducing Claude Duet</media:title>
<media:description>Claude Duet is a research preview: two people and Claude work in one conversation, available by waitlist today.</media:description></media:group></entry>
<entry><id>yt:video:v2</id><yt:videoId>v2</yt:videoId><yt:channelId>UCother</yt:channelId>
<title>Someone else's video</title>
<link rel="alternate" href="https://www.youtube.com/watch?v=v2"/>
<published>2026-10-19T16:00:00+00:00</published>
<media:group><media:description>Not this channel's.</media:description></media:group></entry>
</feed>"""


def test_a_channel_video_is_read_from_its_description_not_its_watch_page():
    """A watch page is a script shell (139-163 characters of footer, 2026-10-21): the
    channel's own video carries its description as text, and nothing is followed."""
    drafts = feed.parse(YOUTUBE, feed_url=YOUTUBE_FEED, today=TODAY)
    assert [(d["title"], d["text"]) for d in drafts] == [
        (
            "Introducing Claude Duet",
            "Claude Duet is a research preview: two people and Claude work in one conversation,"
            " available by waitlist today.",
        ),
        ("Someone else's video", ""),  # another channel's: no description taken, Follow decides
    ]


def test_an_anchor_item_is_read_from_its_own_summary():
    """Each Claude Platform release note is an #anchor on one overview page: Follow would
    give every item the same page."""
    body = RSS.replace(
        "<description>A short teaser the screen cannot judge.</description>",
        "<description>&lt;p&gt;We launched the Files API.&lt;/p&gt;</description>",
    ).replace("https://blog.example.org/team-post/", "https://code.example.org/notes#october-18")
    drafts = feed.parse(body, feed_url=FEED_URL, today=TODAY)
    (note,) = [d for d in drafts if d["url"].endswith("#october-18")]
    assert note["text"] == "We launched the Files API."


def test_an_item_with_empty_content_is_left_out_not_followed():
    body = RSS.replace(
        "<content:encoded><![CDATA[<p><strong>Added</strong></p><ul>",
        "<content:encoded><![CDATA[ ]]></content:encoded><x><![CDATA[<ul>",
    ).replace(
        "</ul>]]></content:encoded></item>\n<item><title>Team",
        "</ul>]]></x></item>\n<item><title>Team",
        1,
    )
    assert [d["title"] for d in feed.parse(body, feed_url=FEED_URL, today=TODAY)] == ["Team post"]


async def test_a_one_line_release_is_screened():
    body = RSS.replace(
        """<li>Added <code>/auto-mode-setup</code>, a guided setup that reads your project</li>
<li>Added a warning when resuming would use a noticeable share of the usage limit</li>""",
        "<li>Fixed a crash on resume</li>",
    )
    client = _client({FEED_URL: httpx2.Response(200, text=body)})
    out = await feed.adapter(TODAY, FEED_URL).fetch(
        client, b.line(), FEED_URL, now=b.T0, env=NO_ENV
    )
    release = next(s for s in _ok(out) if s.title == "2.1.304")
    assert len(release.text) < 200
    assert not no_abstract(release)  # full content: complete at any length


async def test_another_hosts_item_is_read_from_its_page_not_the_feed():
    """A community feed that starts carrying content must not put its own words under an
    official URL: only the feed's own host is taken at its word (security review)."""
    scrape = "https://raw.example-mirror.org/feeds/feed_claude.xml"
    body = RSS.replace(
        "<description>A short teaser the screen cannot judge.</description>",
        "<content:encoded><![CDATA[<p>Words the scrape wrote, not the blog.</p>]]></content:encoded>",
    )
    (post,) = [
        d
        for d in feed.parse(body, feed_url=scrape, today=TODAY)
        if d["url"] == "https://blog.example.org/team-post/"
    ]
    assert post["text"] == ""  # Follow reads the linked page
    client = _client(
        {
            scrape: httpx2.Response(200, text=body),
            "https://blog.example.org/team-post/": httpx2.Response(200, text=ARTICLE),
        }
    )
    out = await feed.adapter(TODAY, scrape).fetch(client, b.line(), scrape, now=b.T0, env=NO_ENV)
    fetched = next(s for s in _ok(out) if s.url == "https://blog.example.org/team-post/")
    assert "minimum review a change needs" in fetched.text
    assert "Words the scrape wrote" not in fetched.text


@pytest.mark.parametrize(
    ("url", "followed"),
    [
        ("https://claude.dev/blog/post/", True),
        ("http://claude.dev/blog/post/", False),
        ("https://127.0.0.1/admin", False),
        ("https://[::1]/admin", False),
        ("https://localhost/admin", False),
        ("https://printer.local/status", False),
        ("https://intranet/wiki", False),
    ],
)
def test_follow_asks_only_named_public_https_hosts(url: str, followed: bool):
    from jev_research_pipeline.adapters.base import (
        _public_https,  # pyright: ignore[reportPrivateUsage]
    )

    assert _public_https(url) is followed


async def test_two_results_that_land_on_one_page_are_one_source():
    """A stage's outputs are unique ids: a moved page listed under its old and new URL is
    stored once, the second counted."""
    body = SITEMAP.replace(
        "</urlset>",
        "<url><loc>https://www.example.org/engineering/old/new-post</loc>"
        "<lastmod>2026-10-19T12:00:00.000Z</lastmod></url></urlset>",
    )
    client = _client(
        {
            "https://www.example.org/sitemap.xml": httpx2.Response(200, text=body),
            "https://www.example.org/engineering/new-post": httpx2.Response(200, text=ARTICLE),
            "https://www.example.org/engineering/old/new-post": httpx2.Response(
                308, headers={"location": "/engineering/new-post"}
            ),
        }
    )
    prefix = "https://www.example.org/engineering/"
    adapter = make_adapter("sitemap", today=TODAY, query=prefix)
    out = await adapter.fetch(client, b.line(), prefix, now=b.T0, env=NO_ENV)
    assert [s.url for s in _ok(out)] == ["https://www.example.org/engineering/new-post"]
    assert out.skipped == 1


def test_a_video_or_anchor_with_no_summary_is_left_out_not_followed():
    video = YOUTUBE.replace(
        "<media:description>Claude Duet is a research preview: two people and Claude work in one"
        " conversation, available by waitlist today.</media:description>",
        "",
    )
    assert [d["title"] for d in feed.parse(video, feed_url=YOUTUBE_FEED, today=TODAY)] == [
        "Someone else's video"
    ]


def test_a_cassette_keeps_a_redirects_location():
    from jev_research_pipeline.cassette import KEPT_HEADERS

    assert "location" in KEPT_HEADERS
