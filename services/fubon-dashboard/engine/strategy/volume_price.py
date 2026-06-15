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
        curr_volume: int,
        avg_volume: float,   # 近期 1min K 棒平均量（排除 VWAP）
        curr_close: float,
        prev_close: float,
    ) -> int:
        points = 0
        # 委買壓力：委買比率 ≥ 65%（主動買盤，買方積極）
        if self.check_bid_imbalance(bid_total, ask_total):
            points += 1
        # 量爆發 ≥ 均量 × 1.5（徒升必有量）
        if avg_volume > 0 and curr_volume >= avg_volume * 1.5:
            points += 1
        # 價格上升（當分鐘收 > 前分鐘收）
        if prev_close > 0 and curr_close > prev_close:
            points += 1
        # 超強量 ≥ 均量 × 3（額外加分，量翻倍爆量）
        if avg_volume > 0 and curr_volume >= avg_volume * 3.0:
            points += 1
        return points
