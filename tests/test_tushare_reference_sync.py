import pandas as pd

from openstockagent.data.models import Instrument, InstrumentAlias
from openstockagent.pipelines.tushare_reference import run_tushare_reference_sync


def test_tushare_reference_sync_maps_reference_status_and_adjustments():
    market_data_storage = FakeMarketDataStorage()
    market_reality_storage = FakeMarketRealityStorage()

    result = run_tushare_reference_sync(
        start="2026-05-25",
        end="2026-05-29",
        status_date="2026-05-28",
        reference_feed=FakeTushareReferenceFeed(),
        market_data_storage=market_data_storage,
        market_reality_storage=market_reality_storage,
    )

    assert result.instruments_written == 2
    assert result.aliases_written == 2
    assert result.calendar_days_written == 2
    assert result.statuses_written == 3
    assert result.corporate_actions_written == 2
    assert [instrument.instrument_id for instrument in market_data_storage.instruments] == [
        "EQUITY:CN:000001",
        "EQUITY:CN:600519",
    ]
    assert market_reality_storage.calendar_days[0].calendar_date == "2026-05-28"
    assert market_reality_storage.calendar_days[0].is_trading_day is True

    statuses = {status.instrument_id: status for status in market_reality_storage.statuses}
    assert statuses["EQUITY:CN:000001"].is_st is True
    assert statuses["EQUITY:CN:000001"].is_tradable is True
    assert statuses["EQUITY:CN:000002"].is_suspended is True
    assert statuses["EQUITY:CN:000002"].is_tradable is False
    assert statuses["EQUITY:CN:600519"].limit_up == 103.0
    assert statuses["EQUITY:CN:600519"].limit_down == 97.0

    actions = {action.action_id: action for action in market_reality_storage.corporate_actions}
    assert actions["tushare-adj-factor-600519.SH-2026-05-28"].adjustment_factor == 10.5
    assert actions["tushare-adj-factor-000001.SZ-2026-05-28"].action_type == "adjustment_factor"


class FakeTushareReferenceFeed:
    def fetch_instruments(self, list_status):
        assert list_status == "L"
        return (
            [
                Instrument("EQUITY:CN:000001", "000001", "CN", "SZSE", "equity", "CNY", "平安银行", "Asia/Shanghai"),
                Instrument("EQUITY:CN:600519", "600519", "CN", "SSE", "equity", "CNY", "贵州茅台", "Asia/Shanghai"),
            ],
            [
                InstrumentAlias("EQUITY:CN:000001", "tushare", "000001.SZ"),
                InstrumentAlias("EQUITY:CN:600519", "tushare", "600519.SH"),
            ],
        )

    def fetch_trade_calendar(self, start, end, exchange):
        assert (start, end, exchange) == ("2026-05-25", "2026-05-29", "SSE")
        return pd.DataFrame(
            {
                "exchange": ["SSE", "SSE"],
                "cal_date": ["20260528", "20260529"],
                "is_open": [1, 0],
                "pretrade_date": ["20260527", "20260528"],
            }
        )

    def fetch_stock_st(self, trade_date):
        assert trade_date == "2026-05-28"
        return pd.DataFrame(
            {
                "ts_code": ["000001.SZ"],
                "name": ["平安银行"],
                "trade_date": ["20260528"],
            }
        )

    def fetch_suspend(self, trade_date):
        assert trade_date == "2026-05-28"
        return pd.DataFrame(
            {
                "ts_code": ["000002.SZ"],
                "trade_date": ["20260528"],
                "suspend_type": ["S"],
            }
        )

    def fetch_stk_limit(self, trade_date):
        assert trade_date == "2026-05-28"
        return pd.DataFrame(
            {
                "ts_code": ["000001.SZ", "000002.SZ", "600519.SH"],
                "trade_date": ["20260528", "20260528", "20260528"],
                "up_limit": [11.0, 22.0, 103.0],
                "down_limit": [9.0, 18.0, 97.0],
            }
        )

    def fetch_adj_factor(self, trade_date):
        assert trade_date == "2026-05-28"
        return pd.DataFrame(
            {
                "ts_code": ["600519.SH", "000001.SZ"],
                "trade_date": ["20260528", "20260528"],
                "adj_factor": [10.5, 2.0],
            }
        )


class FakeMarketDataStorage:
    def __init__(self):
        self.instruments = []
        self.aliases = []

    def upsert_instrument(self, instrument):
        self.instruments.append(instrument)

    def upsert_instrument_alias(self, alias):
        self.aliases.append(alias)


class FakeMarketRealityStorage:
    def __init__(self):
        self.calendar_days = []
        self.statuses = []
        self.corporate_actions = []

    def upsert_trading_calendar_days(self, days):
        self.calendar_days.extend(days)
        return len(days)

    def upsert_instrument_statuses(self, statuses):
        self.statuses.extend(statuses)
        return len(statuses)

    def upsert_corporate_actions(self, actions):
        self.corporate_actions.extend(actions)
        return len(actions)
