from openstockagent.data.models import Instrument, InstrumentAlias


def to_source_symbol(instrument_id: str, source: str) -> str:
    asset_type, market, symbol = instrument_id.split(":", 2)
    if asset_type != "EQUITY":
        raise ValueError(f"Unsupported instrument id: {instrument_id}")
    if source == "akshare":
        if market == "CN":
            return symbol
        raise ValueError(f"Unsupported market for AKShare symbol mapping: {market}")
    if source != "yahoo":
        raise ValueError(f"Unsupported source for symbol mapping: {source}")
    if market == "US":
        return symbol
    if market == "HK":
        return f"{str(int(symbol))}.HK"
    if market == "CN":
        suffix = "SS" if symbol.startswith("6") else "SZ"
        return f"{symbol}.{suffix}"
    raise ValueError(f"Unsupported market for Yahoo symbol mapping: {market}")


def infer_instrument(source_symbol: str, source: str) -> tuple[Instrument, InstrumentAlias]:
    if source_symbol.endswith(".HK"):
        raw = source_symbol[:-3].zfill(5)
        instrument = Instrument(
            instrument_id=f"EQUITY:HK:{raw}",
            symbol=raw,
            market="HK",
            exchange="HKEX",
            asset_type="equity",
            currency="HKD",
            name=None,
            timezone="Asia/Hong_Kong",
        )
    elif source_symbol.endswith(".SH") or source_symbol.endswith(".SZ"):
        raw, suffix = source_symbol.split(".")
        exchange = "SSE" if suffix == "SH" else "SZSE"
        instrument = Instrument(
            instrument_id=f"EQUITY:CN:{raw}",
            symbol=raw,
            market="CN",
            exchange=exchange,
            asset_type="equity",
            currency="CNY",
            name=None,
            timezone="Asia/Shanghai",
        )
    else:
        raw = source_symbol.upper()
        instrument = Instrument(
            instrument_id=f"EQUITY:US:{raw}",
            symbol=raw,
            market="US",
            exchange=None,
            asset_type="equity",
            currency="USD",
            name=None,
            timezone="America/New_York",
        )
    return instrument, InstrumentAlias(instrument.instrument_id, source, source_symbol)
