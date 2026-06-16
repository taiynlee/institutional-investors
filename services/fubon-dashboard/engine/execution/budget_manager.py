import math


class BudgetManager:
    def __init__(
        self,
        max_per_entry: float = 1_000_000,
    ):
        self.max_per_entry = max_per_entry  # 每次進場資金上限（元）

    def calculate_lots(
        self,
        price: float,
        remaining_budget: float,
    ) -> int:
        """每次進場張數 = min(max_per_entry, remaining_budget) / (price × 1000)"""
        if price <= 0:
            return 0
        cap = min(self.max_per_entry, remaining_budget)
        return math.floor(cap / (price * 1000))
