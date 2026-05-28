"""End-to-end China A-share daily stock-selection pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field

from openstockagent.data.readiness import DataReadinessCheck, check_selection_data_readiness
from openstockagent.entry.models import EntryPlanRunResult
from openstockagent.entry.runner import run_entry_plan_pipeline
from openstockagent.entry.rules import ready_plan_ids_by_recommendation
from openstockagent.market.models import MarketContextSnapshot
from openstockagent.market.regime import build_market_context_snapshot
from openstockagent.portfolio.decision import PortfolioDecisionResult, build_default_policy, build_portfolio_decision
from openstockagent.portfolio.models import PortfolioAccount
from openstockagent.recommendations.runner import RecommendationRunResult, run_recommendation_pipeline
from openstockagent.pipelines.real_data_factors import StoredBarFactorRunResult, run_stored_bar_factor_pipeline
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
    entry: EntryPlanRunResult | None = None
    technical: StoredBarFactorRunResult | None = None
    data_readiness: DataReadinessCheck | None = None
    market_context: MarketContextSnapshot | None = None
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
    entry_storage=None,
    portfolio_storage=None,
    horizon: str = "5d",
    market_regime: str = "auto",
    top_n: int = 10,
    min_turnover: float = 0.0,
    min_bar_count: int = 0,
    max_symbols: int | None = None,
    run_reference: bool = True,
    run_daily_sync: bool = True,
    run_technical_factors: bool = True,
    run_entry_plans: bool = True,
    technical_lookback_days: int = 365,
    run_portfolio: bool = True,
    account_id: str = "paper-cn",
    capital: float = 100000.0,
    base_currency: str = "CNY",
    allow_watch_allocation: bool = False,
) -> CNDailySelectionResult:
    reference_result = None
    daily_result = None
    technical_result = None
    messages = []
    market_context = None
    effective_market_regime = market_regime
    market_context_snapshot_id = None

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

    if run_technical_factors:
        technical_result = run_stored_bar_factor_pipeline(
            universe_id=universe_id,
            as_of=trade_date,
            interval="1d",
            lookback_days=technical_lookback_days,
            universe_storage=universe_storage,
            bar_storage=market_data_storage,
            factor_storage=factor_storage,
            max_symbols=max_symbols,
        )
    else:
        messages.append("technical_factor_sync_skipped")

    data_readiness = check_selection_data_readiness(
        universe_id=universe_id,
        as_of=trade_date,
        market="CN",
        universe_storage=universe_storage,
        bar_storage=market_data_storage,
        factor_storage=factor_storage,
        market_reality_storage=market_reality_storage,
        interval="1d",
        adjustment="split_adjusted",
    )
    messages.append(data_readiness.to_message())

    if market_regime == "auto":
        market_context = build_market_context_snapshot(
            universe_id=universe_id,
            as_of=trade_date,
            market="CN",
            universe_storage=universe_storage,
            factor_storage=factor_storage,
        )
        effective_market_regime = market_context.risk_regime
        market_context_snapshot_id = market_context.snapshot_id
        if hasattr(market_reality_storage, "upsert_market_context_snapshot"):
            market_reality_storage.upsert_market_context_snapshot(market_context)
        else:
            messages.append("market_context_storage_skipped")

    if data_readiness.should_block_recommendations:
        effective_market_regime = "data_bad"
        messages.append(f"market_regime_overridden_by_data_readiness={data_readiness.data_status}")

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
        market_context_snapshot_id=market_context_snapshot_id,
    )

    recommendation_result = run_recommendation_pipeline(
        screen_run_id=screening_result.run_id,
        universe_id=universe_id,
        recommendation_date=trade_date,
        horizon=horizon,
        screening_storage=screening_storage,
        recommendation_storage=recommendation_storage,
        market_regime=effective_market_regime,
        config={"max_items": top_n},
    )

    entry_result = None
    entry_plan_ids_by_recommendation_id = {}
    if run_entry_plans:
        if entry_storage is None:
            messages.append("entry_plan_skipped")
        else:
            entry_result = run_entry_plan_pipeline(
                recommendation_run_id=recommendation_result.run_id,
                as_of=trade_date,
                horizon=horizon,
                market_regime=effective_market_regime,
                recommendation_storage=recommendation_storage,
                bar_storage=market_data_storage,
                entry_storage=entry_storage,
                market_reality_storage=market_reality_storage,
                source="tushare",
                adjustment="split_adjusted",
            )
            entry_plan_ids_by_recommendation_id = ready_plan_ids_by_recommendation(entry_result.plans)
    else:
        messages.append("entry_plan_skipped")

    portfolio_result = None
    if run_portfolio:
        if portfolio_storage is None:
            raise ValueError("portfolio_storage is required when run_portfolio=True")
        policy = build_default_policy(allow_watch_allocation=allow_watch_allocation)
        account = PortfolioAccount(account_id=account_id, base_currency=base_currency, capital=capital)
        items = recommendation_storage.load_recommendation_items(recommendation_result.run_id, actionable_only=True)
        if entry_result is not None:
            items = [item for item in items if item.recommendation_id in entry_plan_ids_by_recommendation_id]
        portfolio_result = build_portfolio_decision(
            recommendation_run_id=recommendation_result.run_id,
            account_id=account_id,
            decision_date=trade_date,
            market_regime=effective_market_regime,
            capital=capital,
            policy=policy,
            recommendation_items=items,
            entry_plan_ids_by_recommendation_id=entry_plan_ids_by_recommendation_id,
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
        technical=technical_result,
        entry=entry_result,
        market_context=market_context,
        screening=screening_result,
        recommendation=recommendation_result,
        portfolio=portfolio_result,
        messages=messages,
        data_readiness=data_readiness,
    )
