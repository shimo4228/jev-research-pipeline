"""A web page as text: the canary probe's page, and the page a listing points at (base.Follow).

Regex, not an HTML parser: the text only needs to be readable by the screen and the claim
detector, and a page that defeats the regexes yields less text, never an exception.
"""

import html
import re
from typing import Final

from .base import RawDraft, one_line

TAG: Final = re.compile(r"<(script|style)\b.*?</\1>|<[^>]+>", re.DOTALL | re.IGNORECASE)
_TITLE: Final = re.compile(r"<title[^>]*>(.*?)</title>", re.DOTALL | re.IGNORECASE)
_MAIN: Final = re.compile(r"<(main|article)\b.*?</\1>", re.DOTALL | re.IGNORECASE)
_BLOCK_END: Final = re.compile(
    r"<br\s*/?>|</(?:p|li|h[1-6]|div|tr|blockquote|pre|dt|dd)\s*>", re.IGNORECASE
)
PAGE_CHARS: Final = 4000
"""The canary's excerpt: enough to judge whether the screen still keeps it."""
ARTICLE_CHARS: Final = 12000
"""A followed page is the source itself (an engineering post, a blog article), and its claims
come from its text: the screen reads an excerpt window anyway (jev.context.EXCERPT_CHARS)."""


def strip_tags(fragment: str) -> str:
    """Text of an HTML fragment on one line: tags, scripts and styles removed, entities read."""
    return one_line(html.unescape(TAG.sub(" ", fragment)))


def html_lines(fragment: str) -> str:
    """Text of an HTML fragment with each block (paragraph, list item, heading) on its own
    line: pipeline.units cuts a unit at a newline, so a release note's bullets — most of
    which end without a full stop — become one unit each instead of a 600-character run."""
    lines = (strip_tags(part) for part in _BLOCK_END.split(fragment) if part)
    return "\n".join(line for line in lines if line)


def page_parse(url: str, body: str, *, chars: int = PAGE_CHARS) -> list[RawDraft]:
    """Title and text of a page; the <main> or <article> element when there is one, so
    the navigation that opens most docs pages does not fill the excerpt."""
    found = _TITLE.search(body)
    title = one_line(html.unescape(found.group(1))) if found else url
    main = _MAIN.search(body)
    content = main.group(0) if main else body
    text = strip_tags(content)[:chars]
    return [RawDraft(url=url, title=title, text=text, published_at=None)]


def article_parse(url: str, body: str) -> list[RawDraft]:
    """A followed page (base.Follow.parse): page_parse with the article's longer excerpt."""
    return page_parse(url, body, chars=ARTICLE_CHARS)
