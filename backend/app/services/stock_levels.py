"""
支撐壓力位階計算模組
資料來源：daily_price（OHLCV）＋ institutional（法人買賣超）
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.signal import argrelextrema


def calc_levels(
    price_df: pd.DataFrame,
    inst_df: pd.DataFrame,
) -> dict:
    """
    price_df  columns: trade_date(date), open, high, low, close, volume
    inst_df   columns: trade_date(date), three_major_net
    """
    if price_df.empty or len(price_df) < 20:
        return {'current_price': 0.0, 'supports': [], 'resistances': []}

    df = _prepare(price_df, inst_df)
    cur_price = float(df['close'].iloc[-1])
    latest_date = df['trade_date'].iloc[-1].strftime('%Y-%m-%d')

    supports: list[dict] = []
    resistances: list[dict] = []

    _signal_ma(df, cur_price, latest_date, supports, resistances)
    _signal_volume_candle(df, cur_price, supports, resistances)
    _signal_inst_chip(df, cur_price, supports, resistances)
    _signal_inst_cost(df, cur_price, latest_date, supports, resistances)
    _signal_big_volume(df, cur_price, supports, resistances)
    _signal_swing(df, cur_price, supports, resistances)
    _signal_trendline(df, cur_price, latest_date, supports, resistances)
    _signal_round_number(cur_price, latest_date, supports, resistances)

    sup_levels = _merge_levels(supports,    cur_price, is_support=True)
    res_levels = _merge_levels(resistances, cur_price, is_support=False)

    return {
        'current_price': cur_price,
        'supports':    _format(sup_levels),
        'resistances': _format(res_levels),
    }


def _prepare(price_df: pd.DataFrame, inst_df: pd.DataFrame) -> pd.DataFrame:
    df = price_df.copy()
    df['trade_date'] = pd.to_datetime(df['trade_date']).dt.normalize()
    df = df.sort_values('trade_date').reset_index(drop=True)
    df['vol_ma20'] = df['volume'].rolling(20).mean()

    if not inst_df.empty:
        inst = inst_df.copy()
        inst['trade_date'] = pd.to_datetime(inst['trade_date'])
        inst = inst[['trade_date', 'three_major_net']].rename(
            columns={'three_major_net': 'net_buy'})
        df = df.merge(inst, on='trade_date', how='left')
    else:
        df['net_buy'] = np.nan

    return df.tail(380).reset_index(drop=True)


def _signal_ma(df, cur_price, latest_date, sup, res):
    for period in [5, 10, 20, 60, 120, 240]:
        if len(df) < period:
            continue
        val = round(float(df['close'].rolling(period).mean().iloc[-1]), 2)
        if np.isnan(val):
            continue
        entry = {'date': latest_date, 'price': val, 'type': f'MA{period}'}
        (sup if val < cur_price else res).append(entry)


def _signal_volume_candle(df, cur_price, sup, res):
    if len(df) < 2:
        return
    prev = df.iloc[-2]
    vol_ma = prev['vol_ma20']
    if pd.isna(vol_ma) or prev['volume'] <= vol_ma:
        return
    date_str = str(prev['trade_date'].date())
    if prev['close'] > prev['open'] and prev['low'] < cur_price:
        sup.append({'date': date_str, 'price': float(prev['low']), 'type': '前日量增紅K低點'})
    if prev['close'] < prev['open'] and prev['high'] > cur_price:
        res.append({'date': date_str, 'price': float(prev['high']), 'type': '前日量增黑K高點'})


def _signal_inst_chip(df, cur_price, sup, res):
    chip_df = df.tail(60).dropna(subset=['net_buy'])
    if len(chip_df) < 5:
        return
    std = chip_df['net_buy'].std()
    if std <= 0:
        return
    for _, r in chip_df[
        (chip_df['net_buy'] > std) & (chip_df['close'] > chip_df['open'])
    ].iterrows():
        p = float(r['low'])
        date_str = r['trade_date'].strftime('%Y-%m-%d')
        (sup if p < cur_price else res).append({'date': date_str, 'price': p, 'type': '法人大買紅K底部'})
    for _, r in chip_df[
        (chip_df['net_buy'] < -std) & (chip_df['close'] < chip_df['open'])
    ].iterrows():
        p = float(r['high'])
        date_str = r['trade_date'].strftime('%Y-%m-%d')
        (res if p > cur_price else sup).append({'date': date_str, 'price': p, 'type': '法人大賣黑K頂部'})


def _signal_inst_cost(df, cur_price, latest_date, sup, res):
    chip_df = df.tail(60).dropna(subset=['net_buy'])
    buy_days = chip_df[chip_df['net_buy'] > 0].copy()
    if buy_days.empty or buy_days['net_buy'].sum() <= 0:
        return
    buy_days['typical'] = (buy_days['high'] + buy_days['low'] + buy_days['close']) / 3
    cost = float((buy_days['typical'] * buy_days['net_buy']).sum() / buy_days['net_buy'].sum())
    if cost <= 0:
        return
    entry = {'date': latest_date, 'price': round(cost, 2), 'type': '60日法人成本防線'}
    (sup if cost < cur_price else res).append(entry)


def _signal_big_volume(df, cur_price, sup, res):
    recent = df.tail(120)
    top3 = recent.nlargest(3, 'volume')
    for _, row in top3.iterrows():
        date_str = row['trade_date'].strftime('%Y-%m-%d')
        price = float(row['close'])
        entry = {'date': date_str, 'price': price}
        if price > cur_price:
            res.append({**entry, 'type': '大量套牢區'})
        else:
            sup.append({**entry, 'type': '大量換手支撐'})


def _signal_swing(df, cur_price, sup, res):
    if len(df) < 30:
        return
    order = 10
    highs = df['high'].values
    lows  = df['low'].values
    max_idx = argrelextrema(highs, np.greater_equal, order=order)[0]
    min_idx = argrelextrema(lows,  np.less_equal,   order=order)[0]
    for i in max_idx[-3:]:
        p = float(highs[i])
        date_str = df['trade_date'].iloc[i].strftime('%Y-%m-%d')
        (res if p >= cur_price else sup).append({'date': date_str, 'price': p, 'type': '波段壓力'})
    for i in min_idx[-3:]:
        p = float(lows[i])
        date_str = df['trade_date'].iloc[i].strftime('%Y-%m-%d')
        (sup if p <= cur_price else res).append({'date': date_str, 'price': p, 'type': '波段支撐'})


def _signal_trendline(df, cur_price, latest_date, sup, res):
    if len(df) < 30:
        return
    order = 10
    cur_idx = len(df) - 1
    max_idx = argrelextrema(df['high'].values, np.greater_equal, order=order)[0]
    min_idx = argrelextrema(df['low'].values,  np.less_equal,   order=order)[0]

    if len(max_idx) >= 2:
        i1, i2 = max_idx[-2], max_idx[-1]
        if i1 != i2 and i2 < cur_idx:
            slope = (df['high'].iloc[i2] - df['high'].iloc[i1]) / (i2 - i1)
            proj = df['high'].iloc[i2] + slope * (cur_idx - i2)
            if proj > cur_price:
                res.append({'date': latest_date, 'price': round(float(proj), 2), 'type': '近期高點連線'})

    if len(min_idx) >= 2:
        i1, i2 = min_idx[-2], min_idx[-1]
        if i1 != i2 and i2 < cur_idx:
            slope = (df['low'].iloc[i2] - df['low'].iloc[i1]) / (i2 - i1)
            proj = df['low'].iloc[i2] + slope * (cur_idx - i2)
            if 0 < proj < cur_price:
                sup.append({'date': latest_date, 'price': round(float(proj), 2), 'type': '近期低點連線'})


def _signal_round_number(cur_price, latest_date, sup, res):
    step = 10 if cur_price < 100 else (50 if cur_price < 500 else 100)
    lower = float((cur_price // step) * step)
    upper = lower + step
    if lower != cur_price:
        sup.append({'date': latest_date, 'price': lower, 'type': '整數關卡'})
    if upper != cur_price:
        res.append({'date': latest_date, 'price': upper, 'type': '整數關卡'})


CLUSTER_THRESHOLD = 0.015


def _merge_levels(signals: list[dict], cur_price: float, is_support: bool) -> list[dict]:
    if not signals:
        return []

    filtered = [s for s in signals if abs(s['price'] - cur_price) / cur_price <= 0.20]
    if not filtered:
        return []

    filtered.sort(key=lambda s: abs(s['price'] - cur_price))

    clusters: list[dict] = []
    for s in filtered:
        price = s['price']
        merged = False
        for c in clusters:
            if abs(price - c['mean_price']) / c['mean_price'] <= CLUSTER_THRESHOLD:
                c['prices'].append(price)
                c['signals'].append(s)
                c['mean_price'] = sum(c['prices']) / len(c['prices'])
                merged = True
                break
        if not merged:
            clusters.append({'prices': [price], 'mean_price': price, 'signals': [s]})

    clusters.sort(key=lambda c: abs(c['mean_price'] - cur_price))
    clusters = clusters[:5]
    clusters.sort(key=lambda c: c['mean_price'], reverse=is_support)

    result = []
    for c in clusters:
        mean_p = round(c['mean_price'], 2)
        if is_support and mean_p >= cur_price:
            continue
        if not is_support and mean_p <= cur_price:
            continue
        pct = round((mean_p - cur_price) / cur_price * 100, 1)
        seen = set()
        details = []
        for s in sorted(c['signals'], key=lambda x: x['date'], reverse=True):
            key = (s['date'], s['type'])
            if key not in seen:
                seen.add(key)
                details.append({'date': s['date'], 'type': s['type']})
        result.append({
            'price': mean_p,
            'pct': pct,
            'signal_count': len(c['prices']),
            'details': details,
        })
    return result


def _format(levels: list[dict]) -> list[dict]:
    return levels
