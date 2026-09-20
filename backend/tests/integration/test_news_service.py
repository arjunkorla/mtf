import pytest
from sqlalchemy import select

from app.models.news import NewsItem
from app.models.stock import Stock
from app.services.news_service import get_fresh_news_for_stock

pytestmark = pytest.mark.asyncio


async def test_matched_news_is_upserted_and_returned(db_session):
    stock = Stock(symbol="NSE:RELIANCE-EQ", company_name="Reliance Industries Ltd", sector="Energy")
    db_session.add(stock)
    await db_session.flush()

    rows = await get_fresh_news_for_stock(db_session, stock.id, "NSE:RELIANCE-EQ", "Reliance Industries Ltd")

    assert len(rows) == 1
    assert "Reliance Industries" in rows[0].headline
    assert rows[0].category == "Results"
    assert rows[0].sentiment == "POSITIVE"
    assert rows[0].source == "Economic Times"
    assert rows[0].source_url.startswith("https://")


async def test_unrelated_stock_yields_empty(db_session):
    stock = Stock(symbol="NSE:UNRELATEDCO-EQ", company_name="Totally Unrelated Corp", sector=None)
    db_session.add(stock)
    await db_session.flush()

    rows = await get_fresh_news_for_stock(db_session, stock.id, "NSE:UNRELATEDCO-EQ", "Totally Unrelated Corp")
    assert rows == []


async def test_rerun_does_not_duplicate_rows(db_session):
    stock = Stock(symbol="NSE:TCS-EQ", company_name="Tata Consultancy Services Ltd", sector="IT")
    db_session.add(stock)
    await db_session.flush()

    first = await get_fresh_news_for_stock(db_session, stock.id, "NSE:TCS-EQ", "Tata Consultancy Services Ltd")
    second = await get_fresh_news_for_stock(db_session, stock.id, "NSE:TCS-EQ", "Tata Consultancy Services Ltd")

    assert len(first) == 1
    assert len(second) == 1  # not duplicated

    all_rows = (await db_session.execute(select(NewsItem).where(NewsItem.stock_id == stock.id))).scalars().all()
    assert len(all_rows) == 1


async def test_news_engine_reads_back_what_was_stored(db_session):
    """End-to-end: news_service writes, app/engines/news_engine.py (untouched)
    reads -- confirms the two sides of the seam agree on shape."""
    from app.engines.news_engine import build_news_data

    stock = Stock(symbol="NSE:HDFCBANK-EQ", company_name="HDFC Bank Ltd", sector="Financials")
    db_session.add(stock)
    await db_session.flush()

    rows = await get_fresh_news_for_stock(db_session, stock.id, "NSE:HDFCBANK-EQ", "HDFC Bank Ltd")
    news_data = build_news_data(rows)

    assert len(news_data.items) == 1
    assert news_data.items[0].sentiment == "NEGATIVE"
    assert news_data.overall_sentiment == "NEGATIVE"
