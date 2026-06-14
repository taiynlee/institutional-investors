import math


class BudgetManager:
    def __init__(
        self,
        total_capital: float,
        risk_per_trade_pct: float,
        max_position_capital: float = 0,
    ):
        self.total_capital = total_capital
        self.risk_per_trade_pct = risk_per_trade_pct
        self.max_position_capital = max_position_capital  # 0 = no limit

    def calculate_lots(
        self,
        atr: float,
        atr_multiplier: float,
        price: float,
        remaining_budget: float,
    ) -> int:
        risk_amount = self.total_capital * self.risk_per_trade_pct / 100
        stop_points = atr_multiplier * atr
        if stop_points == 0:
            return 0
        std_lots = math.floor(risk_amount / (stop_points * 1000))
        budget_lots = math.floor(remaining_budget / (price * 1000))
        if self.max_position_capital > 0:
            capital_lots = math.floor(self.max_position_capital / (price * 1000))
            return min(std_lots, capital_lots, budget_lots)
        return min(std_lots, budget_lots)
