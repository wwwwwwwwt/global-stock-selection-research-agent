"""Core stock universe builders for China and US markets."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
import csv
from io import StringIO

import pandas as pd
import requests

from openstockagent.data.models import Instrument, InstrumentAlias
from openstockagent.universe.models import Universe, UniverseMember


CN_CORE_INDICES = {
    "csi300": "000300",
    "csi500": "000905",
}

US_CORE_INDICES = {
    "sp500": "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
    "nasdaq100": "https://en.wikipedia.org/wiki/Nasdaq-100",
}


@dataclass(frozen=True)
class CoreUniverseBuildResult:
    universe: Universe
    members: list[UniverseMember]
    instruments: list[Instrument]
    aliases: list[InstrumentAlias]


def build_cn_core_universe(
    *,
    as_of: str,
    universe_id: str = "cn_core",
    name: str = "China A-share Core",
    index_symbols: dict[str, str] | None = None,
    custom_csv_paths: list[Path] | None = None,
    client=None,
) -> CoreUniverseBuildResult:
    client = client or _import_akshare()
    members = OrderedDict()
    instruments = {}
    aliases = {}
    for index_name, index_symbol in (index_symbols or CN_CORE_INDICES).items():
        frame = client.index_stock_cons_csindex(symbol=index_symbol)
        for symbol, stock_name in _cn_constituents(frame):
            instrument_id = f"EQUITY:CN:{symbol}"
            _merge_member(members, universe_id, instrument_id, as_of, f"index:{index_name}")
            instruments[instrument_id] = _cn_instrument(symbol, stock_name)
            aliases[(instrument_id, "akshare", symbol)] = InstrumentAlias(instrument_id, "akshare", symbol)

    _merge_custom_csv_members(members, instruments, aliases, universe_id, as_of, custom_csv_paths or [])
    return CoreUniverseBuildResult(
        universe=Universe(
            universe_id=universe_id,
            name=name,
            market="CN",
            asset_type="equity",
            description="沪深300 + 中证500 + 自定义行业龙头",
        ),
        members=list(members.values()),
        instruments=list(instruments.values()),
        aliases=list(aliases.values()),
    )


def build_us_core_universe(
    *,
    as_of: str,
    universe_id: str = "us_core",
    name: str = "US Equity Core",
    include_indices: tuple[str, ...] = ("sp500", "nasdaq100"),
    custom_csv_paths: list[Path] | None = None,
    html_reader=None,
) -> CoreUniverseBuildResult:
    html_reader = html_reader or _read_html_tables
    members = OrderedDict()
    instruments = {}
    aliases = {}
    for index_name in include_indices:
        url = US_CORE_INDICES[index_name]
        frame = _select_us_constituent_table(html_reader(url))
        for symbol, stock_name in _us_constituents(frame):
            instrument_id = f"EQUITY:US:{symbol}"
            _merge_member(members, universe_id, instrument_id, as_of, f"index:{index_name}")
            instruments[instrument_id] = _us_instrument(symbol, stock_name)
            aliases[(instrument_id, "polygon", symbol)] = InstrumentAlias(instrument_id, "polygon", symbol)
            aliases[(instrument_id, "yahoo", symbol)] = InstrumentAlias(instrument_id, "yahoo", symbol)

    _merge_custom_csv_members(members, instruments, aliases, universe_id, as_of, custom_csv_paths or [])
    return CoreUniverseBuildResult(
        universe=Universe(
            universe_id=universe_id,
            name=name,
            market="US",
            asset_type="equity",
            description="S&P 500 + Nasdaq 100 + custom theme watchlist",
        ),
        members=list(members.values()),
        instruments=list(instruments.values()),
        aliases=list(aliases.values()),
    )


def persist_core_universe(result: CoreUniverseBuildResult, universe_storage, market_data_storage) -> int:
    universe_storage.upsert_universe(result.universe)
    for instrument in result.instruments:
        market_data_storage.upsert_instrument(instrument)
    for alias in result.aliases:
        market_data_storage.upsert_instrument_alias(alias)
    return universe_storage.upsert_universe_members(result.members)


def _merge_member(members: OrderedDict[str, UniverseMember], universe_id: str, instrument_id: str, as_of: str, reason: str) -> None:
    existing = members.get(instrument_id)
    if existing is None:
        members[instrument_id] = UniverseMember(universe_id, instrument_id, as_of, reason=reason)
        return
    reasons = _append_reason(existing.reason, reason)
    members[instrument_id] = UniverseMember(universe_id, instrument_id, existing.start_date, existing.end_date, reasons)


def _append_reason(existing: str | None, reason: str) -> str:
    parts = [] if not existing else existing.split(",")
    if reason not in parts:
        parts.append(reason)
    return ",".join(parts)


def _cn_constituents(frame: pd.DataFrame) -> list[tuple[str, str | None]]:
    symbol_column = _first_existing_column(frame, ["成分券代码", "品种代码", "证券代码", "代码", "symbol"])
    name_column = _first_existing_column(frame, ["成分券名称", "品种名称", "证券简称", "名称", "name"], required=False)
    rows = []
    for _, row in frame.iterrows():
        symbol = str(row[symbol_column]).strip().split(".")[0].zfill(6)
        stock_name = str(row[name_column]).strip() if name_column else None
        rows.append((symbol, stock_name))
    return rows


def _us_constituents(frame: pd.DataFrame) -> list[tuple[str, str | None]]:
    symbol_column = _first_existing_column(frame, ["Symbol", "Ticker", "Ticker symbol"])
    name_column = _first_existing_column(frame, ["Security", "Company", "Company Name", "Name"], required=False)
    rows = []
    for _, row in frame.iterrows():
        symbol = str(row[symbol_column]).strip().replace(" ", "")
        stock_name = str(row[name_column]).strip() if name_column else None
        if symbol and symbol.lower() != "nan":
            rows.append((symbol.upper(), stock_name))
    return rows


def _select_us_constituent_table(tables: list[pd.DataFrame]) -> pd.DataFrame:
    for table in tables:
        columns = {str(column) for column in table.columns}
        if columns & {"Symbol", "Ticker", "Ticker symbol"}:
            return table
    raise ValueError("No US index constituent table found")


def _read_html_tables(url: str) -> list[pd.DataFrame]:
    response = requests.get(
        url,
        headers={
            "User-Agent": "OpenStockAgent/0.1 stock-selection-research",
            "Accept-Language": "en-US,en;q=0.9",
        },
        timeout=20,
    )
    response.raise_for_status()
    return pd.read_html(StringIO(response.text))


def _merge_custom_csv_members(
    members: OrderedDict[str, UniverseMember],
    instruments: dict[str, Instrument],
    aliases: dict[tuple[str, str, str], InstrumentAlias],
    universe_id: str,
    as_of: str,
    paths: list[Path],
) -> None:
    for path in paths:
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                instrument_id = row.get("instrument_id") or _instrument_id_from_market_symbol(row["market"], row["symbol"])
                symbol = instrument_id.split(":")[-1]
                reason = row.get("reason") or f"custom:{path.stem}"
                _merge_member(members, universe_id, instrument_id, row.get("start_date") or as_of, reason)
                if instrument_id not in instruments:
                    instruments[instrument_id] = _instrument_from_id(instrument_id, row.get("name"))
                source = "akshare" if ":CN:" in instrument_id else "polygon"
                aliases[(instrument_id, source, symbol)] = InstrumentAlias(instrument_id, source, symbol)


def _instrument_id_from_market_symbol(market: str, symbol: str) -> str:
    market = market.upper()
    if market == "CN":
        return f"EQUITY:CN:{symbol.zfill(6)}"
    if market == "US":
        return f"EQUITY:US:{symbol.upper()}"
    raise ValueError(f"Unsupported custom universe market: {market}")


def _instrument_from_id(instrument_id: str, name: str | None) -> Instrument:
    _, market, symbol = instrument_id.split(":", 2)
    if market == "CN":
        return _cn_instrument(symbol, name)
    if market == "US":
        return _us_instrument(symbol, name)
    raise ValueError(f"Unsupported instrument id: {instrument_id}")


def _cn_instrument(symbol: str, name: str | None) -> Instrument:
    exchange = "SSE" if symbol.startswith("6") else "SZSE"
    return Instrument(
        instrument_id=f"EQUITY:CN:{symbol}",
        symbol=symbol,
        market="CN",
        exchange=exchange,
        asset_type="equity",
        currency="CNY",
        name=name,
        timezone="Asia/Shanghai",
    )


def _us_instrument(symbol: str, name: str | None) -> Instrument:
    return Instrument(
        instrument_id=f"EQUITY:US:{symbol}",
        symbol=symbol,
        market="US",
        exchange=None,
        asset_type="equity",
        currency="USD",
        name=name,
        timezone="America/New_York",
    )


def _first_existing_column(frame: pd.DataFrame, names: list[str], required: bool = True) -> str | None:
    for name in names:
        if name in frame.columns:
            return name
    if required:
        raise ValueError(f"Missing expected column. Available columns: {list(frame.columns)}")
    return None


def _import_akshare():
    import akshare as ak

    return ak
