import datetime as dt

from app.data.news_matcher import RawNewsItem, classify_category, classify_sentiment, matches_company, parse_rss_feed
from app.integrations.news.rss_feed_client import _MOCK_RSS_XML


def test_parse_rss_feed_extracts_all_items():
    items = parse_rss_feed(_MOCK_RSS_XML)
    assert len(items) == 4
    first = items[0]
    assert "Reliance Industries" in first.title
    assert first.link.startswith("https://")
    assert first.published_at.year == 2026


def test_parse_rss_feed_handles_garbage_gracefully():
    assert parse_rss_feed("not xml at all") == []
    assert parse_rss_feed("<rss></rss>") == []


def test_parse_rss_feed_skips_item_with_unparseable_date():
    xml = """<rss><channel><item>
        <title>Some headline</title>
        <link>https://example.com/a</link>
        <pubDate>not a date</pubDate>
    </item></channel></rss>"""
    assert parse_rss_feed(xml) == []


def test_matches_company_by_ticker():
    items = parse_rss_feed(_MOCK_RSS_XML)
    tcs_item = next(i for i in items if "TCS" in i.title)
    assert matches_company(tcs_item, "TCS", "Tata Consultancy Services Ltd")


def test_matches_company_by_distinctive_name_phrase():
    items = parse_rss_feed(_MOCK_RSS_XML)
    reliance_item = next(i for i in items if "Reliance" in i.title)
    # Ticker "RIL" isn't in the text -- this specifically exercises the
    # name-phrase path (generic "Ltd" suffix stripped, "Reliance Industries"
    # required as a phrase).
    assert matches_company(reliance_item, "RIL", "Reliance Industries Ltd")


def test_matches_company_does_not_cross_contaminate_group_companies():
    """Regression test: matching on just the first word of the company name
    ("Tata") previously caused a TCS headline to also match Tata Motors."""
    items = parse_rss_feed(_MOCK_RSS_XML)
    tcs_item = next(i for i in items if "TCS" in i.title)
    assert not matches_company(tcs_item, "TATAMOTORS", "Tata Motors Ltd")
    assert matches_company(tcs_item, "TCS", "Tata Consultancy Services Ltd")


def test_matches_company_no_false_positive_for_unrelated_stock():
    items = parse_rss_feed(_MOCK_RSS_XML)
    reliance_item = next(i for i in items if "Reliance" in i.title)
    assert not matches_company(reliance_item, "INFY", "Infosys Ltd")


def test_matches_company_rejects_short_name_phrases():
    """A name phrase under 3 chars (e.g. a stray initial after stripping
    corporate suffixes) shouldn't be used for matching -- too likely to
    produce false positives -- even if it technically appears in the text."""
    item = RawNewsItem(
        title="AI stocks rally on strong earnings across the board",
        description="A broad rally in artificial-intelligence-linked names.",
        link="https://example.com/ai-rally",
        published_at=dt.datetime.now(dt.UTC),
    )
    assert not matches_company(item, "XY", "AI Ltd")


def test_classify_category_results():
    items = parse_rss_feed(_MOCK_RSS_XML)
    reliance_item = next(i for i in items if "Reliance" in i.title)
    assert classify_category(reliance_item) == "Results"


def test_classify_category_orders():
    items = parse_rss_feed(_MOCK_RSS_XML)
    tcs_item = next(i for i in items if "TCS" in i.title)
    assert classify_category(tcs_item) == "Orders"


def test_classify_category_regulatory():
    items = parse_rss_feed(_MOCK_RSS_XML)
    hdfc_item = next(i for i in items if "HDFC" in i.title)
    assert classify_category(hdfc_item) == "Regulatory"


def test_classify_category_sector_wide_item():
    items = parse_rss_feed(_MOCK_RSS_XML)
    generic_item = next(i for i in items if "Gainers" in i.title)
    # The mock item's description mentions "sectors" -- a defensible
    # Sector-events classification, not the catch-all.
    assert classify_category(generic_item) == "Sector events"


def test_classify_category_falls_back_to_corporate_announcements_with_no_keyword_hits():
    item = RawNewsItem(
        title="XYZ Ltd appoints new chief financial officer",
        description="The company announced a routine leadership change effective next month.",
        link="https://example.com/xyz-cfo",
        published_at=dt.datetime.now(dt.UTC),
    )
    assert classify_category(item) == "Corporate announcements"


def test_classify_sentiment_positive_and_negative():
    items = parse_rss_feed(_MOCK_RSS_XML)
    reliance_item = next(i for i in items if "Reliance" in i.title)
    hdfc_item = next(i for i in items if "HDFC" in i.title)
    assert classify_sentiment(reliance_item) == "POSITIVE"
    assert classify_sentiment(hdfc_item) == "NEGATIVE"
