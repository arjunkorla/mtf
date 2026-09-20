"""Parses RSS feed XML into raw items and matches them against a specific
stock (section 13). Never invents an article -- only surfaces items that
were actually fetched and whose text actually mentions the company.

Category and sentiment classification are simple, auditable keyword rules
(same spirit as news_engine.py's existing sentiment classifier) rather than
an ML model -- easy to see exactly why an item was labeled a certain way.
"""

import datetime as dt
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from email.utils import parsedate_to_datetime

from app.logging_config import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class RawNewsItem:
    title: str
    description: str
    link: str
    published_at: dt.datetime


def parse_rss_feed(raw_xml: str) -> list[RawNewsItem]:
    try:
        root = ET.fromstring(raw_xml)
    except ET.ParseError as exc:
        logger.warning("Failed to parse RSS feed XML: %s", exc)
        return []

    items: list[RawNewsItem] = []
    for item_el in root.findall(".//item"):
        title = (item_el.findtext("title") or "").strip()
        description = (item_el.findtext("description") or "").strip()
        link = (item_el.findtext("link") or "").strip()
        pub_date_raw = (item_el.findtext("pubDate") or "").strip()

        if not title or not link:
            continue

        try:
            published_at = parsedate_to_datetime(pub_date_raw)
            if published_at.tzinfo is None:
                published_at = published_at.replace(tzinfo=dt.UTC)
        except (TypeError, ValueError):
            logger.warning("Skipping RSS item with unparseable pubDate %r: %s", pub_date_raw, title)
            continue

        items.append(RawNewsItem(title=title, description=description, link=link, published_at=published_at))

    return items


_GENERIC_SUFFIXES = {"ltd", "ltd.", "limited", "inc", "inc.", "corp", "corp.", "corporation", "co", "co.", "plc"}


def _distinctive_name_phrase(company_name: str) -> str:
    """The company name with only trailing generic corporate suffixes
    stripped -- e.g. "Tata Consultancy Services Ltd" -> "Tata Consultancy
    Services", "Tata Motors Ltd" -> "Tata Motors".

    Deliberately NOT just the first word: many Indian conglomerates list
    several separate companies sharing one group name (Tata Motors, Tata
    Steel, Tata Consultancy Services, Tata Power, ...), so matching on
    "Tata" alone would cross-contaminate one group company's news onto all
    the others. Requiring the fuller phrase trades a little recall (an
    article using only "Tata Motors" as "Tata" won't match) for precision
    that actually matters here.
    """
    words = company_name.split()
    while words and words[-1].lower().rstrip(".") in _GENERIC_SUFFIXES:
        words.pop()
    return " ".join(words) if words else company_name


def matches_company(item: RawNewsItem, ticker: str, company_name: str) -> bool:
    """Whole-word, case-insensitive match against the ticker or the
    company's distinctive name phrase, checked in the title+description.

    This is a heuristic, not a guarantee: it can miss articles that refer to
    a company by an unrelated short form, and in rare cases a ticker could
    coincide with an unrelated common word. It never fabricates a match --
    only a real substring hit counts.
    """
    text = f"{item.title} {item.description}"
    ticker_pattern = re.compile(rf"\b{re.escape(ticker)}\b", re.IGNORECASE)
    if ticker_pattern.search(text):
        return True

    name_phrase = _distinctive_name_phrase(company_name)
    if len(name_phrase) < 3:
        return False
    name_pattern = re.compile(rf"\b{re.escape(name_phrase)}\b", re.IGNORECASE)
    return bool(name_pattern.search(text))


_CATEGORY_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("Results", ("results", "profit", "revenue", "earnings", "quarterly", "q1 ", "q2 ", "q3 ", "q4 ")),
    ("Orders", ("order", "contract", "bags", "wins deal", "wins a", "deal win")),
    ("Acquisitions", ("acquisition", "acquire", "acquires", "stake sale", "merger", "buyout", "block deal")),
    ("Expansion", ("expansion", "expand", "new plant", "new facility", "capacity")),
    ("Regulatory", ("rbi", "sebi", "regulatory", "government", "ministry", "tribunal", "probe", "investigation")),
    ("Sector events", ("sector", "industry-wide", "industry")),
]


def classify_category(item: RawNewsItem) -> str:
    text = f"{item.title} {item.description}".lower()
    for category, keywords in _CATEGORY_KEYWORDS:
        if any(kw in text for kw in keywords):
            return category
    return "Corporate announcements"


_POSITIVE_KEYWORDS = (
    "beats estimates", "beats view", "record profit", "order win", "bags", "wins deal", "expansion",
    "upgrade", "buyback", "rally", "surge", "jump", "gain", "rises", "up 1", "up 2", "up 3",
)
_NEGATIVE_KEYWORDS = (
    "misses estimates", "downgrade", "fraud", "investigation", "default", "resignation", "probe",
    "concerns", "slide", "falls", "plunge", "crash", "down 1", "down 2", "down 3",
)


def classify_sentiment(item: RawNewsItem) -> str:
    text = f"{item.title} {item.description}".lower()
    if any(kw in text for kw in _POSITIVE_KEYWORDS):
        return "POSITIVE"
    if any(kw in text for kw in _NEGATIVE_KEYWORDS):
        return "NEGATIVE"
    return "NEUTRAL"
