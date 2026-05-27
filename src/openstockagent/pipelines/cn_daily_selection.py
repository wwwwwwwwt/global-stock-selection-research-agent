"""End-to-end China A-share daily stock-selection pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field

from openstockagent.portfolio.decision import PortfolioDecisionResult, build_default_policy, build_portfolio_decision
from openstockagent.portfolio.models import PortfolioAccount
from openstockagent.recommendations.runner import RecommendationRunResult, run_recommendation_pipeline
from openstockagent.screening.runner import ScreeningRunResult, run_screening_pipeline
from openstockagent.screening.scoring import build_default_strategy

from .tushare_daily_batch import TushareDailyBatchSyncResult, run_tushare_daily_batch_sync
from .tushare_reference import TushareReferenceSyncResult, run_tushare_reference_sync


@dataclass(frozen=True)
class CNDailySelectionResult:
    universe_id: str
    trade_date: str
    reference: TushareReferenceSyncResult | None
    daily: TushareDailyBatchSyncResult | None
    screening: ScreeningRunResult
    recommendation: RecommendationRunResult
    portfolio: PortfolioDecisionResult | None = None
    messages: list[str] = field(default_factory=list)


def run_cn_daily_selection_pipeline(
    *,
    universe_id: str,
    trade_date: str,
    reference_start: str,
    reference_feed,
    universe_storage,
    market_data_storage,
    market_reality_storage,
    factor_storage,
    screening_storage,
    recommendation_storage,
    portfolio_storage=None,
    horizon: str = "5d",
    market_regime: str = "neutral",
    top_n: int = 10,
    min_turnover: float = 0.0,
    min_bar_count: int = 0,
    max_symbols: int | None = None,
    run_reference: bool = True,
    run_daily_sync: bool = True,
    run_portfolio: bool = True,
    account_id: str = "paper-cn",
    capital: float = 100000.0,
    base_currency: str = "CNY",
) -> CNDailySelectionResult:
    reference_result = None
    daily_result = None
    messages = []

    if run_reference:
        reference_result = run_tushare_reference_sync(
            start=reference_start,
            end=trade_date,
            status_date=trade_date,
            reference_feed=reference_feed,
            market_data_storage=market_data_storage,
            market_reality_storage=market_reality_storage,
        )
    else:
        messages.append("reference_sync_skipped")

    if run_daily_sync:
        daily_result = run_tushare_daily_batch_sync(
            universe_id=universe_id,
            trade_date=trade_date,
            reference_feed=reference_feed,
            universe_storage=universe_storage,
            bar_storage=market_data_storage,
            factor_storage=factor_storage,
            max_symbols=max_symbols,
        )
    else:
        messages.append("daily_sync_skipped")

    strategy = build_default_strategy(
        hard_filters={
            "min_turnover_amount_20d": min_turnover,
            "min_bar_count": min_bar_count,
        },
        max_candidates=top_n,
    )
    screening_result = run_screening_pipeline(
        universe_id=universe_id,
        as_of=trade_date,
        interval="1d",
        universe_storage=universe_storage,
        factor_storage=factor_storage,
        screening_storage=screening_storage,
        market_reality_storage=market_reality_storage,
        strategy=strategy,
    )

    recommendation_result = run_recommendation_pipeline(
        screen_run_id=screening_result.run_id,
        universe_id=universe_id,
        recommendation_date=trade_date,
        horizon=horizon,
        screening_storage=screening_storage,
        recommendation_storage=recommendation_storage,
        market_regime=market_regime,
        config={"max_items": top_n},
    )

    portfolio_result = None
    if run_portfolio:
        if portfolio_storage is None:
            raise ValueError("portfolio_storage is required when run_portfolio=True")
        policy = build_default_policy()
        account = PortfolioAccount(account_id=account_id, base_currency=base_currency, capital=capital)
        items = recommendation_storage.load_recommendation_items(recommendation_result.run_id, actionable_only=True)
        portfolio_result = build_portfolio_decision(
            recommendation_run_id=recommendation_result.run_id,
            account_id=account_id,
            decision_date=trade_date,
            market_regime=market_regime,
            capital=capital,
            policy=policy,
            recommendation_items=items,
        )
        portfolio_storage.upsert_account(account)
        portfolio_storage.upsert_policy(policy)
        portfolio_storage.upsert_decision(portfolio_result.decision)
        portfolio_storage.delete_target_allocations(portfolio_result.decision.decision_id)
        portfolio_storage.upsert_target_allocations(portfolio_result.allocations)
    else:
        messages.append("portfolio_skipped")

    return CNDailySelectionResult(
        universe_id=universe_id,
        trade_date=trade_date,
        reference=reference_result,
        daily=daily_result,
        screening=screening_result,
        recommendation=recommendation_result,
        portfolio=portfolio_result,
        messages=messages,
    )
