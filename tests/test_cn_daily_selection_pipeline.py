import pandas as pd

from openstockagent.data.models import Instrument, InstrumentAlias
from openstockagent.pipelines.cn_daily_selection import run_cn_daily_selection_pipeline
from openstockagent.screening.models import ScreenResult
from openstockagent.universe.models import UniverseMember


def test_cn_daily_selection_pipeline_runs_data_screen_recommendation_and_portfolio():
    universe_storage = FakeUniverseStorage(
        [
            UniverseMember("cn_core", "EQUITY:CN:000001", "2026-01-01"),
            UniverseMember("cn_core", "EQUITY:CN:600519", "2026-01-01"),
        ]
    )
    market_data_storage = FakeMarketDataStorage()
    market_reality_storage = FakeMarketRealityStorage()
    factor_storage = FakeFactorStorage()
    screening_storage = FakeScreeningStorage()
    recommendation_storage = FakeRecommendationStorage()
    portfolio_storage = FakePortfolioStorage()

    result = run_cn_daily_selection_pipeline(
        universe_id="cn_core",
        trade_date="2026-05-27",
        reference_start="2026-05-20",
        reference_feed=FakeTushareReferenceFeed(),
        universe_storage=universe_storage,
        market_data_storage=market_data_storage,
        market_reality_storage=market_reality_storage,
        factor_storage=factor_storage,
        screening_storage=screening_storage,
        recommendation_storage=recommendation_storage,
        portfolio_storage=portfolio_storage,
        top_n=2,
        market_regime="neutral",
        capital=100000,
    )

    assert result.reference is not None
    assert result.reference.instruments_written == 2
    assert result.daily is not None
    assert result.daily.bars_written == 2
    assert result.daily.factor_values_written == 18
    assert result.screening.selected_count == 2
    assert result.recommendation.buy_candidate_count >= 1
    assert result.portfolio is not None
    assert result.portfolio.decision.action == "allocate"
    assert portfolio_storage.account.account_id == "paper-cn"
    assert portfolio_storage.allocations


def test_cn_daily_selection_pipeline_keeps_cash_when_only_watch_recommendations():
    universe_storage = FakeUniverseStorage([UniverseMember("cn_core", "EQUITY:CN:000001", "2026-01-01")])
    market_data_storage = FakeMarketDataStorage()
    market_reality_storage = FakeMarketRealityStorage()
    factor_storage = FakeFactorStorage()
    screening_storage = FakeScreeningStorage(
        preset_results=[
            ScreenResult(
                run_id="screen-ce51b9a266f3b376",
                instrument_id="EQUITY:CN:000001",
                rank=1,
                selected=True,
                total_score=0.60,
                score_breakdown_json="{}",
                reason_json="{}",
                risk_json="{}",
                evidence_refs_json="{}",
            )
        ]
    )
    recommendation_storage = FakeRecommendationStorage()
    portfolio_storage = FakePortfolioStorage()

    result = run_cn_daily_selection_pipeline(
        universe_id="cn_core",
        trade_date="2026-05-27",
        reference_start="2026-05-20",
        reference_feed=FakeWatchOnlyReferenceFeed(),
        universe_storage=universe_storage,
        market_data_storage=market_data_storage,
        market_reality_storage=market_reality_storage,
        factor_storage=factor_storage,
        screening_storage=screening_storage,
        recommendation_storage=recommendation_storage,
        portfolio_storage=portfolio_storage,
        top_n=1,
        market_regime="neutral",
        capital=100000,
        run_reference=False,
        run_daily_sync=False,
    )

    assert result.recommendation.buy_candidate_count == 0
    assert result.recommendation.watch_count == 1
    assert result.portfolio is not None
    assert result.portfolio.decision.action == "no_new_position"
    assert result.portfolio.decision.cash_pct == 1.0
    assert result.portfolio.allocations == []


class FakeTushareReferenceFeed:
    def fetch_instruments(self, list_status):
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
        return pd.DataFrame({"cal_date": ["20260527"], "is_open": [1]})

    def fetch_stock_st(self, trade_date):
        return pd.DataFrame(columns=["ts_code", "trade_date"])

    def fetch_suspend(self, trade_date):
        return pd.DataFrame(columns=["ts_code", "trade_date"])

    def fetch_stk_limit(self, trade_date):
        return pd.DataFrame(
            {
                "ts_code": ["000001.SZ", "600519.SH"],
                "trade_date": ["20260527", "20260527"],
                "up_limit": [11.0, 110.0],
                "down_limit": [9.0, 90.0],
            }
        )

    def fetch_adj_factor(self, trade_date):
        return pd.DataFrame(
            {
                "ts_code": ["000001.SZ", "600519.SH"],
                "trade_date": ["20260527", "20260527"],
                "adj_factor": [2.0, 10.0],
            }
        )

    def fetch_daily(self, trade_date):
        return pd.DataFrame(
            {
                "ts_code": ["000001.SZ", "600519.SH"],
                "trade_date": ["20260527", "20260527"],
                "open": [10.0, 100.0],
                "high": [10.5, 103.0],
                "low": [9.8, 99.0],
                "close": [10.2, 101.0],
                "vol": [1000.0, 2000.0],
                "amount": [1000.0, 2000.0],
            }
        )

    def fetch_daily_basic(self, trade_date):
        return pd.DataFrame(
            {
                "ts_code": ["000001.SZ", "600519.SH"],
                "trade_date": ["20260527", "20260527"],
                "turnover_rate": [3.0, 1.0],
                "turnover_rate_f": [4.0, 1.5],
                "volume_ratio": [2.0, 0.8],
                "pe_ttm": [8.0, 30.0],
                "pb": [0.8, 5.0],
                "ps_ttm": [1.0, 8.0],
                "dv_ttm": [4.0, 1.0],
                "total_mv": [2000000.0, 1000000.0],
                "circ_mv": [1500000.0, 800000.0],
            }
        )


class FakeWatchOnlyReferenceFeed(FakeTushareReferenceFeed):
    def fetch_instruments(self, list_status):
        return (
            [
                Instrument("EQUITY:CN:000001", "000001", "CN", "SZSE", "equity", "CNY", "平安银行", "Asia/Shanghai"),
            ],
            [
                InstrumentAlias("EQUITY:CN:000001", "tushare", "000001.SZ"),
            ],
        )

    def fetch_stk_limit(self, trade_date):
        return pd.DataFrame(
            {
                "ts_code": ["000001.SZ"],
                "trade_date": ["20260527"],
                "up_limit": [11.0],
                "down_limit": [9.0],
            }
        )

    def fetch_adj_factor(self, trade_date):
        return pd.DataFrame({"ts_code": ["000001.SZ"], "trade_date": ["20260527"], "adj_factor": [2.0]})

    def fetch_daily(self, trade_date):
        return pd.DataFrame(
            {
                "ts_code": ["000001.SZ"],
                "trade_date": ["20260527"],
                "open": [10.0],
                "high": [10.5],
                "low": [9.8],
                "close": [10.2],
                "vol": [1000.0],
                "amount": [1000.0],
            }
        )

    def fetch_daily_basic(self, trade_date):
        return pd.DataFrame(
            {
                "ts_code": ["000001.SZ"],
                "trade_date": ["20260527"],
                "turnover_rate": [1.0],
                "turnover_rate_f": [1.0],
                "volume_ratio": [1.0],
                "pe_ttm": [20.0],
                "pb": [2.0],
                "ps_ttm": [2.0],
                "dv_ttm": [1.0],
                "total_mv": [100000.0],
                "circ_mv": [80000.0],
            }
        )


class FakeUniverseStorage:
    def __init__(self, members):
        self.members = members

    def load_universe_members(self, universe_id, as_of=None):
        return self.members


class FakeMarketDataStorage:
    def upsert_instruments(self, instruments):
        self.instruments = instruments
        return len(instruments)

    def upsert_instrument_aliases(self, aliases):
        self.aliases = aliases
        return len(aliases)

    def upsert_bars(self, frame):
        self.bars = frame
        return len(frame)


class FakeMarketRealityStorage:
    def __init__(self):
        self.statuses = {}

    def upsert_trading_calendar_days(self, days):
        self.calendar_days = days
        return len(days)

    def upsert_instrument_statuses(self, statuses):
        self.statuses = {status.instrument_id: status for status in statuses}
        return len(statuses)

    def upsert_corporate_actions(self, actions):
        self.actions = actions
        return len(actions)

    def load_instrument_status(self, instrument_id, as_of):
        return self.statuses.get(instrument_id)


class FakeFactorStorage:
    def __init__(self):
        self.values = []

    def upsert_factor_definitions(self, definitions):
        self.definitions = definitions
        return len(definitions)

    def upsert_factor_values(self, values):
        self.values = values
        return len(values)

    def load_factor_values(self, trade_date, interval):
        return self.values


class FakeScreeningStorage:
    def __init__(self, preset_results=None):
        self.preset_results = preset_results

    def upsert_strategy(self, strategy):
        self.strategy = strategy

    def upsert_screen_run(self, run):
        self.run = run

    def delete_screen_results(self, run_id):
        self.deleted_run_id = run_id
        return 0

    def upsert_screen_results(self, results):
        self.results = self.preset_results if self.preset_results is not None else results
        return len(results)

    def load_screen_results(self, run_id, selected_only=False):
        results = getattr(self, "results", [])
        if selected_only:
            return [result for result in results if result.selected]
        return results


class FakeRecommendationStorage:
    def upsert_recommendation_run(self, run):
        self.run = run

    def delete_recommendation_items(self, run_id):
        self.deleted_run_id = run_id
        return 0

    def upsert_recommendation_items(self, items):
        self.items = items
        return len(items)

    def load_recommendation_items(self, run_id, actionable_only=False):
        items = getattr(self, "items", [])
        if actionable_only:
            return [item for item in items if item.action in {"buy_candidate", "watch"}]
        return items


class FakePortfolioStorage:
    def upsert_account(self, account):
        self.account = account

    def upsert_policy(self, policy):
        self.policy = policy

    def upsert_decision(self, decision):
        self.decision = decision

    def delete_target_allocations(self, decision_id):
        self.deleted_decision_id = decision_id
        return 0

    def upsert_target_allocations(self, allocations):
        self.allocations = allocations
        return len(allocations)
