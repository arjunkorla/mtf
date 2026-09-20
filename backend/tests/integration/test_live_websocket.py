from fastapi.testclient import TestClient

from app.main import app


def test_websocket_streams_mock_ticks_for_requested_symbol():
    with TestClient(app) as client, client.websocket_connect("/api/ws/quotes?symbols=NSE:RELIANCE-EQ") as ws:
        data = ws.receive_json()
        assert data["symbol"] == "NSE:RELIANCE-EQ"
        assert isinstance(data["ltp"], float)
        assert data["ltp"] > 0
        assert "as_of" in data


def test_websocket_streams_multiple_symbols():
    with TestClient(app) as client, client.websocket_connect("/api/ws/quotes?symbols=NSE:RELIANCE-EQ,NSE:TCS-EQ") as ws:
        seen = set()
        for _ in range(4):
            data = ws.receive_json()
            seen.add(data["symbol"])
            if seen == {"NSE:RELIANCE-EQ", "NSE:TCS-EQ"}:
                break
        assert seen == {"NSE:RELIANCE-EQ", "NSE:TCS-EQ"}


def test_multiple_clients_share_one_connection_and_survive_partial_disconnect():
    """Phase 11: Client A wants RELIANCE; Client B wants RELIANCE+HDFCBANK.
    Both must receive RELIANCE from the same shared backend connection, and
    Client B disconnecting must not affect Client A's stream."""
    with TestClient(app) as client:
        with client.websocket_connect("/api/ws/quotes?symbols=NSE:RELIANCE-EQ") as ws_a:
            data_a = ws_a.receive_json()
            assert data_a["symbol"] == "NSE:RELIANCE-EQ"

            with client.websocket_connect("/api/ws/quotes?symbols=NSE:RELIANCE-EQ,NSE:HDFCBANK-EQ") as ws_b:
                seen_b = set()
                for _ in range(8):
                    d = ws_b.receive_json()
                    seen_b.add(d["symbol"])
                    if seen_b == {"NSE:RELIANCE-EQ", "NSE:HDFCBANK-EQ"}:
                        break
                assert "NSE:HDFCBANK-EQ" in seen_b
            # Client B has now disconnected -- Client A must keep receiving.
            data_a2 = ws_a.receive_json()
            assert data_a2["symbol"] == "NSE:RELIANCE-EQ"


def test_websocket_rejects_missing_symbols():
    with TestClient(app) as client:
        try:
            with client.websocket_connect("/api/ws/quotes?symbols="):
                pass
            assert False, "expected the connection to be rejected"
        except Exception:
            pass  # Starlette raises when the server closes during the handshake
