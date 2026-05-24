class FeedRegistry:
    def __init__(self):
        self._feeds = {}

    def register(self, market: str, asset_type: str, interval: str, feed) -> None:
        self._feeds[self._key(market, asset_type, interval)] = feed

    def resolve(self, market: str, asset_type: str, interval: str):
        key = self._key(market, asset_type, interval)
        if key in self._feeds:
            return self._feeds[key]
        fallback = self._key(market, asset_type, "1d")
        if fallback in self._feeds:
            return self._feeds[fallback]
        raise ValueError(f"No feed registered for market={market}, asset_type={asset_type}, interval={interval}")

    def _key(self, market: str, asset_type: str, interval: str) -> tuple[str, str, str]:
        return (market.upper(), asset_type.lower(), interval.lower())
