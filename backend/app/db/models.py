from datetime import date, datetime
from typing import Optional
from sqlalchemy import String, Integer, BigInteger, Float, Boolean, Date, DateTime, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class StockList(Base):
    __tablename__ = "stock_list"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(10), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(50))
    market: Mapped[str] = mapped_column(String(10))  # TWSE / TPEx
    sector: Mapped[str] = mapped_column(String(50))
    tags: Mapped[str] = mapped_column(Text, default="")
    capital: Mapped[float] = mapped_column(Float, default=0)  # 股本（張）
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DailyPrice(Base):
    __tablename__ = "daily_price"
    __table_args__ = (UniqueConstraint("code", "trade_date"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(10), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[int] = mapped_column(Integer)


class Institutional(Base):
    __tablename__ = "institutional"
    __table_args__ = (UniqueConstraint("code", "trade_date"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(10), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    foreign_net: Mapped[float] = mapped_column(Float, default=0)
    trust_net: Mapped[float] = mapped_column(Float, default=0)
    dealer_net: Mapped[float] = mapped_column(Float, default=0)
    three_major_net: Mapped[float] = mapped_column(Float, default=0)


class MarginTrading(Base):
    __tablename__ = "margin_trading"
    __table_args__ = (UniqueConstraint("code", "trade_date"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(10), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    margin_balance: Mapped[int] = mapped_column(BigInteger, default=0)
    margin_change: Mapped[int] = mapped_column(BigInteger, default=0)
    short_balance: Mapped[int] = mapped_column(BigInteger, default=0)
    short_change: Mapped[int] = mapped_column(BigInteger, default=0)


class Shareholding(Base):
    __tablename__ = "shareholding"
    __table_args__ = (UniqueConstraint("code", "report_date"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(10), index=True)
    report_date: Mapped[date] = mapped_column(Date, index=True)
    holders_1000_lot: Mapped[int] = mapped_column(Integer, default=0)
    pct_1000_lot: Mapped[float] = mapped_column(Float, default=0)
    pct_400_lot: Mapped[Optional[float]] = mapped_column(Float, nullable=True, default=0)


class SecuritiesLending(Base):
    __tablename__ = "securities_lending"
    __table_args__ = (UniqueConstraint("code", "trade_date"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(10), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    lending_balance: Mapped[int] = mapped_column(BigInteger, default=0)
    lending_change: Mapped[int] = mapped_column(BigInteger, default=0)


class ScreeningResult(Base):
    __tablename__ = "screening_result"
    __table_args__ = (UniqueConstraint("code", "calc_date"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(10), index=True)
    name: Mapped[str] = mapped_column(String(50))
    calc_date: Mapped[date] = mapped_column(Date, index=True)
    tags: Mapped[str] = mapped_column(Text, default="")
    # BB 指標
    bb_position: Mapped[float] = mapped_column(Float)
    bb_peak: Mapped[float] = mapped_column(Float)
    peak_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    peak_days_ago: Mapped[int] = mapped_column(Integer, default=0)
    is_squeeze: Mapped[bool] = mapped_column(Boolean, default=False)
    # 成交量
    vol_ratio: Mapped[float] = mapped_column(Float)
    # 籌碼
    foreign_6d_net: Mapped[float] = mapped_column(Float, default=0)
    trust_6d_net: Mapped[float] = mapped_column(Float, default=0)
    chip_ratio_1d: Mapped[float] = mapped_column(Float, default=0)
    chip_ratio_6d: Mapped[float] = mapped_column(Float, default=0)
    chip_ratio_12d: Mapped[float] = mapped_column(Float, default=0)
    chip_ratio_20d: Mapped[float] = mapped_column(Float, default=0)
    margin_5d_chg: Mapped[float] = mapped_column(Float, default=0)
    lending_5d_chg: Mapped[float] = mapped_column(Float, default=0)
    holders_1000_chg: Mapped[float] = mapped_column(Float, default=0)
    holders_w2: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    holders_w3: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # RS
    rs_vs_market: Mapped[float] = mapped_column(Float, default=0)
    # 策略 A 專用欄位
    upper_slope: Mapped[float] = mapped_column(Float, default=0)
    ma20_slope: Mapped[float] = mapped_column(Float, default=0)
    close_position: Mapped[float] = mapped_column(Float, default=0)
    change_pct: Mapped[float] = mapped_column(Float, default=0)
    ma5_days: Mapped[int] = mapped_column(Integer, default=0)
    score_a: Mapped[float] = mapped_column(Float, default=0)
    # 評分
    score_b: Mapped[float] = mapped_column(Float, default=0)
    dip_bonus: Mapped[float] = mapped_column(Float, default=0)
    holders_bonus: Mapped[float] = mapped_column(Float, default=0)
    passes: Mapped[bool] = mapped_column(Boolean, default=True)


class WatchlistA(Base):
    __tablename__ = "watchlist_a"
    __table_args__ = (UniqueConstraint("code", "added_date"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(10), index=True)
    name: Mapped[str] = mapped_column(String(50))
    added_date: Mapped[date] = mapped_column(Date, index=True)
    added_close: Mapped[float] = mapped_column(Float, default=0)
    added_bb_position: Mapped[float] = mapped_column(Float, default=0)
    added_score_a: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(20), default="tracking")
    triggered_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    triggered_close: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    triggered_bb_position: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AIPick(Base):
    __tablename__ = "ai_pick"
    id: Mapped[int] = mapped_column(primary_key=True)
    calc_date: Mapped[date] = mapped_column(Date, unique=True, index=True)
    code: Mapped[str] = mapped_column(String(10))
    name: Mapped[str] = mapped_column(String(50))
    reason: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class MonthlyRevenue(Base):
    __tablename__ = "monthly_revenue"
    __table_args__ = (UniqueConstraint("code", "year", "month"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(10), index=True)
    year: Mapped[int] = mapped_column(Integer)
    month: Mapped[int] = mapped_column(Integer)
    revenue: Mapped[float] = mapped_column(Float)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class QuarterlyEps(Base):
    __tablename__ = "quarterly_eps"
    __table_args__ = (UniqueConstraint("code", "year", "quarter"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(10), index=True)
    year: Mapped[int] = mapped_column(Integer)
    quarter: Mapped[int] = mapped_column(Integer)
    eps: Mapped[float] = mapped_column(Float, default=0)
    revenue: Mapped[float] = mapped_column(Float, default=0)
    op_income: Mapped[float] = mapped_column(Float, default=0)
    net_income: Mapped[float] = mapped_column(Float, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class IcClassification(Base):
    __tablename__ = "ic_classification"
    __table_args__ = (UniqueConstraint("code", "ic_code"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(10), index=True)
    name: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    ic_code: Mapped[str] = mapped_column(String(10))
    ic_name: Mapped[str] = mapped_column(String(50))
    ic_parent: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    ic_node: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    ic_position: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CompanyTag(Base):
    __tablename__ = "company_tags"
    __table_args__ = (UniqueConstraint("code", "tag"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(10), index=True)
    tag: Mapped[str] = mapped_column(String(50))


class StockPool(Base):
    __tablename__ = "stock_pool"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(10), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(50), default="")
    added_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class UsWatchlist(Base):
    __tablename__ = "us_watchlist"
    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100), default="")
    added_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class FetchLog(Base):
    __tablename__ = "fetch_log"
    __table_args__ = (UniqueConstraint("job_name", "fetch_date"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    job_name: Mapped[str] = mapped_column(String(50))
    fetch_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20))
    rows_fetched: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
