from datetime import date, datetime
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
    tags: Mapped[str] = mapped_column(Text, default="")  # JSON list as text
    capital: Mapped[float] = mapped_column(Float, default=0)  # 股本（張），用於法人買超比率正規化
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
    foreign_net: Mapped[float] = mapped_column(Float, default=0)  # 外資淨買超（張）
    trust_net: Mapped[float] = mapped_column(Float, default=0)    # 投信淨買超（張）
    dealer_net: Mapped[float] = mapped_column(Float, default=0)   # 自營商淨買超（張）
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


class SecuritiesLending(Base):
    __tablename__ = "securities_lending"
    __table_args__ = (UniqueConstraint("code", "trade_date"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(10), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    lending_balance: Mapped[int] = mapped_column(BigInteger, default=0)   # 借券賣出今日餘額（股）
    lending_change: Mapped[int] = mapped_column(BigInteger, default=0)    # 借券賣出增減（股）


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
    peak_date: Mapped[date] = mapped_column(Date, nullable=True)
    peak_days_ago: Mapped[int] = mapped_column(Integer, default=0)
    is_squeeze: Mapped[bool] = mapped_column(Boolean, default=False)
    # 成交量
    vol_ratio: Mapped[float] = mapped_column(Float)
    # 籌碼（法人用股本正規化）
    foreign_6d_net: Mapped[float] = mapped_column(Float, default=0)
    trust_6d_net: Mapped[float] = mapped_column(Float, default=0)
    chip_ratio_1d: Mapped[float] = mapped_column(Float, default=0)   # (外資+投信)當日/股本 %
    chip_ratio_6d: Mapped[float] = mapped_column(Float, default=0)   # (外資+投信)6日/股本 %
    chip_ratio_12d: Mapped[float] = mapped_column(Float, default=0)  # (外資+投信)12日/股本 %
    margin_5d_chg: Mapped[float] = mapped_column(Float, default=0)   # 融資5日增減%（負=減少=好）
    lending_5d_chg: Mapped[float] = mapped_column(Float, default=0)  # 借券5日增減%（負=減少=好）
    holders_1000_chg: Mapped[float] = mapped_column(Float, default=0)
    # RS
    rs_vs_market: Mapped[float] = mapped_column(Float, default=0)
    # 綜合評分
    score: Mapped[float] = mapped_column(Float, default=0)         # 基礎分
    dip_bonus: Mapped[float] = mapped_column(Float, default=0)     # 資加：下跌日法人買超（每次+1，上限+5）
    holders_bonus: Mapped[float] = mapped_column(Float, default=0) # 戶加：千張大戶週增減%（可負）
    passes: Mapped[bool] = mapped_column(Boolean, default=True)


class AIPick(Base):
    __tablename__ = "ai_pick"
    id: Mapped[int] = mapped_column(primary_key=True)
    calc_date: Mapped[date] = mapped_column(Date, unique=True, index=True)
    code: Mapped[str] = mapped_column(String(10))
    name: Mapped[str] = mapped_column(String(50))
    reason: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class FetchLog(Base):
    __tablename__ = "fetch_log"
    __table_args__ = (UniqueConstraint("job_name", "fetch_date"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    job_name: Mapped[str] = mapped_column(String(50))
    fetch_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20))  # success / failed / skipped
    rows_fetched: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
