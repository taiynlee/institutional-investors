class VolumePriceStrategy:
    def __init__(self, imbalance_threshold: float = 0.65):
        self.imbalance_threshold = imbalance_threshold

    def check_bid_imbalance(self, bid_total: float, ask_total: float) -> bool:
        total = bid_total + ask_total
        if total == 0:
            return False
        return bid_total / total >= self.imbalance_threshold

    def score(
        self,
        bid_total: float,
        ask_total: float,
        outside_ratio: float,
        curr_volume: float,
        prev_volume: float,
        curr_close: float,
        prev_close: float,
        price: float,
        vwap: float,
        vwap_sigma: float,
        vwap_entry_sigma: float,
        vwap_exit_sigma: float,
    ) -> int:
        if price > vwap + vwap_exit_sigma * vwap_sigma:
            return 0

        points = 0
        if self.check_bid_imbalance(bid_total, ask_total):
            points += 1
        if outside_ratio > 0.60:
            points += 1
        if curr_volume > prev_volume:
            points += 1
        if curr_close > prev_close:
            points += 1
        if price >= vwap + vwap_entry_sigma * vwap_sigma:
            points += 1
        return points
