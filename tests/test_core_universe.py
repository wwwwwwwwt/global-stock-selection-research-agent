from pathlib import Path

import pandas as pd

from openstockagent.universe import core
from openstockagent.universe.core import (
    build_cn_core_universe,
    build_us_core_universe,
    persist_core_universe,
)


def test_build_cn_core_universe_merges_csi_indices_and_custom_leaders(tmp_path):
    custom = tmp_path / "leaders.csv"
    custom.write_text(
        "market,symbol,name,start_date,reason\n"
        "CN,600519,贵州茅台,2024-01-01,custom:leader\n"
        "CN,300750,宁德时代,2024-01-01,custom:leader\n",
        encoding="utf-8",
    )
    client = FakeAkshareClient()

    result = build_cn_core_universe(
        as_of="2026-05-25",
        index_symbols={"csi300": "000300", "csi500": "000905"},
        custom_csv_paths=[custom],
        client=client,
    )

    member_by_id = {member.instrument_id: member for member in result.members}
    assert client.calls == ["000300", "000905"]
    assert set(member_by_id) == {"EQUITY:CN:600519", "EQUITY:CN:000001", "EQUITY:CN:300750"}
    assert member_by_id["EQUITY:CN:600519"].reason == "index:csi300,index:csi500,custom:leader"
    assert {instrument.instrument_id for instrument in result.instruments} == set(member_by_id)
    assert {alias.source for alias in result.aliases} == {"akshare"}


def test_build_us_core_universe_merges_sp500_nasdaq100_and_custom_theme(tmp_path):
    custom = tmp_path / "theme.csv"
    custom.write_text(
        "market,symbol,name,start_date,reason\n"
        "US,NVDA,NVIDIA,2024-01-01,custom:ai\n"
        "US,MSFT,Microsoft,2024-01-01,custom:cloud\n",
        encoding="utf-8",
    )

    result = build_us_core_universe(
        as_of="2026-05-25",
        custom_csv_paths=[custom],
        html_reader=fake_us_html_reader,
    )

    member_by_id = {member.instrument_id: member for member in result.members}
    assert set(member_by_id) == {"EQUITY:US:AAPL", "EQUITY:US:MSFT", "EQUITY:US:NVDA"}
    assert member_by_id["EQUITY:US:MSFT"].reason == "index:nasdaq100,custom:cloud"
    assert {alias.source for alias in result.aliases} == {"polygon", "yahoo"}


def test_build_us_core_universe_default_reader_uses_user_agent(monkeypatch):
    calls = {}

    def fake_get(url, headers, timeout):
        calls["url"] = url
        calls["headers"] = headers
        calls["timeout"] = timeout
        return FakeResponse(
            """
            <table>
              <tr><th>Symbol</th><th>Security</th></tr>
              <tr><td>AAPL</td><td>Apple Inc.</td></tr>
            </table>
            """
        )

    monkeypatch.setattr(core.requests, "get", fake_get)

    result = build_us_core_universe(as_of="2026-05-25", include_indices=("sp500",))

    assert calls["headers"]["User-Agent"].startswith("OpenStockAgent/")
    assert calls["timeout"] == 20
    assert [member.instrument_id for member in result.members] == ["EQUITY:US:AAPL"]


def test_persist_core_universe_writes_universe_instruments_aliases_and_members():
    result = build_us_core_universe(as_of="2026-05-25", include_indices=("sp500",), html_reader=fake_us_html_reader)
    universe_storage = FakeUniverseStorage()
    market_data_storage = FakeMarketDataStorage()

    written = persist_core_universe(result, universe_storage, market_data_storage)

    assert universe_storage.universe.universe_id == "us_core"
    assert written == len(result.members)
    assert len(market_data_storage.instruments) == len(result.instruments)
    assert len(market_data_storage.aliases) == len(result.aliases)


class FakeAkshareClient:
    def __init__(self):
        self.calls = []

    def index_stock_cons_csindex(self, symbol):
        self.calls.append(symbol)
        if symbol == "000300":
            return pd.DataFrame(
                {
                    "成分券代码": ["600519", "000001"],
                    "成分券名称": ["贵州茅台", "平安银行"],
                }
            )
        return pd.DataFrame(
            {
                "成分券代码": ["600519"],
                "成分券名称": ["贵州茅台"],
            }
        )


class FakeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


def fake_us_html_reader(url):
    if "Nasdaq" in url:
        return [pd.DataFrame({"Ticker": ["MSFT"], "Company": ["Microsoft"]})]
    return [pd.DataFrame({"Symbol": ["AAPL"], "Security": ["Apple Inc."]})]


class FakeUniverseStorage:
    def upsert_universe(self, universe):
        self.universe = universe

    def upsert_universe_members(self, members):
        self.members = members
        return len(members)


class FakeMarketDataStorage:
    def __init__(self):
        self.instruments = []
        self.aliases = []

    def upsert_instrument(self, instrument):
        self.instruments.append(instrument)

    def upsert_instrument_alias(self, alias):
        self.aliases.append(alias)
