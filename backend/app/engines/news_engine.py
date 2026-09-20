"""News / catalyst engine (section 13).

Only classifies news items that were actually fetched from a source (see
app/models/news.py) -- this engine never invents headlines. Sentiment
classification here is a simple, auditable keyword rule set; swapping in an
NLP/LLM classifier later is a drop-in replacement for `_classify_sentiment`.

No news source integration is wired up yet (Phase 2 TODO: pick a licensed
news/corporate-announcements feed) so `build_news_data` currently returns
whatever rows exist in the `news` table, which will be empty until that
integration lands -- an honest INSUFFICIENT/empty state rather than a mock.
"""

from app.core.constants import NewsSentiment
from app.models.news import NewsItem
from app.schemas.stock import NewsCatalystItem, NewsData

_POSITIVE_KEYWORDS = ("beats estimates", "record profit", "order win", "expansion", "upgrade", "buyback")
_NEGATIVE_KEYWORDS = ("misses estimates", "downgrade", "fraud", "investigation", "default", "resignation")


def _classify_sentiment(headline: str, existing: str | None) -> str:
    if existing and existing in (s.value for s in NewsSentiment):
        return existing
    text = headline.lower()
    if any(k in text for k in _POSITIVE_KEYWORDS):
        return NewsSentiment.POSITIVE.value
    if any(k in text for k in _NEGATIVE_KEYWORDS):
        return NewsSentiment.NEGATIVE.value
    return NewsSentiment.NEUTRAL.value


def build_news_data(items: list[NewsItem]) -> NewsData:
    catalysts = [
        NewsCatalystItem(
            headline=i.headline,
            category=i.category,
            sentiment=_classify_sentiment(i.headline, i.sentiment),
            source=i.source,
            source_url=i.source_url,
            published_at=i.published_at,
        )
        for i in items
    ]

    if not catalysts:
        overall = NewsSentiment.UNKNOWN.value
    else:
        positives = sum(1 for c in catalysts if c.sentiment == NewsSentiment.POSITIVE.value)
        negatives = sum(1 for c in catalysts if c.sentiment == NewsSentiment.NEGATIVE.value)
        if positives > negatives:
            overall = NewsSentiment.POSITIVE.value
        elif negatives > positives:
            overall = NewsSentiment.NEGATIVE.value
        else:
            overall = NewsSentiment.NEUTRAL.value

    return NewsData(items=catalysts, overall_sentiment=overall)
