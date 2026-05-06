"""
Kronos 回测引擎 v2
均值回归 + 动量信号融合策略
数据源：AKShare A股日线数据
"""

import json
import math
import argparse
import time
import sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# ─── 指标计算 ────────────────────────────────────────────────────────────────

def sma(series: pd.Series, n: int) -> pd.Series:
    return series.rolling(n).mean()

def bollinger_bands(series: pd.Series, n: int = 20, k: float = 2.0):
    ma = sma(series, n)
    std = series.rolling(n).std()
    return ma + k * std, ma - k * std, ma

def rsi(series: pd.Series, n: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(n).mean()
    avg_loss = loss.rolling(n).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)

def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast = series.ewm(span=fast).mean()
    ema_slow = series.ewm(span=slow).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram

def volume_sma(vol: pd.Series, n: int = 20) -> pd.Series:
    return vol.rolling(n).mean()

# ─── 信号生成 ────────────────────────────────────────────────────────────────

def generate_signals(df: pd.DataFrame, lookback: int = 20, temperature: float = 0.7) -> pd.DataFrame:
    """
    融合策略信号：
    - 均值回归信号：价格偏离布林带下轨→多，偏离上轨→空
    - 动量信号：MACD 金叉/死叉 + RSI
    - temperature 控制信号置信度阈值
    """
    close = df['close']
    high = df['high']
    low = df['low']
    volume = df['volume']

    # 布林带
    bb_upper, bb_lower, bb_mid = bollinger_bands(close, n=lookback)

    # RSI
    rsi_val = rsi(close, n=14)

    # MACD
    macd_line, signal_line, hist = macd(close)

    # 成交量均线
    vol_ma = volume_sma(volume, n=20)

    signals = []
    for i in range(len(df)):
        price = close.iloc[i]
        bb_u = bb_upper.iloc[i]
        bb_l = bb_lower.iloc[i]
        bb_m = bb_mid.iloc[i]
        rsi_v = rsi_val.iloc[i]
        macd_h = hist.iloc[i]
        vol_ratio = volume.iloc[i] / vol_ma.iloc[i] if vol_ma.iloc[i] > 0 else 1

        if pd.isna(bb_l) or pd.isna(rsi_v) or pd.isna(macd_h):
            signals.append({'signal': 'neutral', 'confidence': 0.5, 'reason': '数据不足'})
            continue

        # ── 均值回归分量（多层次判断）──
        bb_dev = (price - bb_m) / bb_m if bb_m > 0 else 0  # 偏离度（%）
        if price <= bb_l:
            mr_signal = 'long'
            mr_conf = 0.75
        elif price >= bb_u:
            mr_signal = 'short'
            mr_conf = 0.75
        elif bb_dev < -0.02:       # 偏离MA下2%+
            mr_signal = 'long'
            mr_conf = 0.6
        elif bb_dev > 0.02:         # 偏离MA上2%+
            mr_signal = 'short'
            mr_conf = 0.6
        elif bb_dev < -0.01:        # 偏离MA下1%+
            mr_signal = 'long'
            mr_conf = 0.45
        elif bb_dev > 0.01:         # 偏离MA上1%+
            mr_signal = 'short'
            mr_conf = 0.45
        else:
            mr_signal = 'neutral'
            mr_conf = 0.25

        # ── 动量分量 ──
        if rsi_v < 30 and macd_h > 0:
            mom_signal = 'long'
            mom_conf = 0.65
        elif rsi_v > 70 and macd_h < 0:
            mom_signal = 'short'
            mom_conf = 0.65
        elif rsi_v < 40 and macd_h > 0:
            mom_signal = 'long'
            mom_conf = 0.45
        elif rsi_v > 60 and macd_h < 0:
            mom_signal = 'short'
            mom_conf = 0.45
        else:
            mom_signal = 'neutral'
            mom_conf = 0.2

        # ── 融合（温度调节置信度）─┼───────────────────────────────
        signal_votes = {'long': 0.0, 'short': 0.0, 'neutral': 0.0}
        signal_votes[mr_signal] += mr_conf * temperature
        signal_votes[mom_signal] += mom_conf * (1 - temperature)
        # 基准中立票，防止全靠中立票胜出
        signal_votes['neutral'] += 0.1

        final_signal = max(signal_votes, key=signal_votes.get)
        final_conf = signal_votes[final_signal]

        if final_conf < 0.3:
            final_signal = 'neutral'
            reason = '信号模糊，观望'
        elif final_signal == 'long':
            if price <= bb_l:
                reason = f"触及布林下轨，RSI={rsi_v:.0f}"
            elif bb_dev < 0:
                reason = f"偏离MA {bb_dev*100:.1f}%，RSI={rsi_v:.0f}"
            else:
                reason = f"MACD 金叉+RSI={rsi_v:.0f}"
        elif final_signal == 'short':
            if price >= bb_u:
                reason = f"触及布林上轨，RSI={rsi_v:.0f}"
            elif bb_dev > 0:
                reason = f"偏离MA {bb_dev*100:.1f}%，RSI={rsi_v:.0f}"
            else:
                reason = f"MACD 死叉+RSI={rsi_v:.0f}"
        else:
            reason = '无显著偏离'

        signals.append({
            'signal': final_signal,
            'confidence': round(final_conf, 2),
            'price': round(price, 2),
            'reason': reason
        })

    return signals

# ─── 回测引擎 ───────────────────────────────────────────────────────────────

def backtest(df: pd.DataFrame, signals: list, initial_capital: float = 100000) -> dict:
    """
    模拟回测：
    - signal='long' → 全仓买入
    - signal='short' → 平多仓（不做空）
    - signal='neutral' → 观望
    """
    cash = initial_capital
    position = 0  # 持股数量
    equity_curve = []
    trades = []
    wins, losses = 0, 0
    total_pnl = 0
    trade_id = 0

    entry_price = 0
    entry_time = ''
    entry_side = ''

    for i in range(len(df)):
        date = df['date'].iloc[i]
        close = df['close'].iloc[i]
        sig = signals[i]['signal']

        # 持仓市值
        market_value = position * close
        equity = cash + market_value
        equity_curve.append({'date': date, 'strategy': round(equity, 2), 'benchmark': round(initial_capital * (close / df['close'].iloc[0]), 2)})

        # 买入信号
        if sig == 'long' and position == 0:
            position = math.floor(cash / close)
            cost = position * close
            cash -= cost
            entry_price = close
            entry_time = date
            entry_side = 'long'
            trade_id += 1

        # 卖出/平仓信号
        elif sig in ('short', 'neutral') and position > 0:
            revenue = position * close
            pnl = revenue - (position * entry_price)
            pnl_pct = pnl / (position * entry_price) * 100
            holding_days = (datetime.strptime(date, '%Y-%m-%d') - datetime.strptime(entry_time, '%Y-%m-%d')).days
            cash += revenue
            position = 0

            if pnl > 0:
                wins += 1
            else:
                losses += 1
            total_pnl += pnl

            trades.append({
                'id': trade_id,
                'entry': entry_time,
                'exit': date,
                'side': entry_side,
                'entry_price': round(entry_price, 2),
                'exit_price': round(close, 2),
                'pnl': round(pnl, 2),
                'pnl_pct': round(pnl_pct, 2),
                'holding': f"{holding_days}d"
            })

    # 未平仓结算
    if position > 0:
        last_close = df['close'].iloc[-1]
        pnl = position * (last_close - entry_price)
        pnl_pct = pnl / (position * entry_price) * 100
        holding_days = (datetime.strptime(df['date'].iloc[-1], '%Y-%m-%d') - datetime.strptime(entry_time, '%Y-%m-%d')).days
        cash += position * last_close
        trades.append({
            'id': trade_id + 1,
            'entry': entry_time,
            'exit': df['date'].iloc[-1],
            'side': entry_side,
            'entry_price': round(entry_price, 2),
            'exit_price': round(last_close, 2),
            'pnl': round(pnl, 2),
            'pnl_pct': round(pnl_pct, 2),
            'holding': f"{holding_days}d (持仓中)"
        })

    # ── 计算指标 ────────────────────────────────────────────────────────────
    returns = pd.Series([e['strategy'] for e in equity_curve]).pct_change().dropna()
    benchmark_returns = pd.Series([e['benchmark'] for e in equity_curve]).pct_change().dropna()

    if len(returns) > 0:
        sharpe = returns.mean() / returns.std() * math.sqrt(252) if returns.std() > 0 else 0
    else:
        sharpe = 0

    total_trades = wins + losses
    win_rate = wins / total_trades if total_trades > 0 else 0
    avg_pnl = total_pnl / total_trades if total_trades > 0 else 0

    # 预测误差（简化：用信号方向 vs 实际次日涨跌）
    correct_dirs = 0
    dir_total = 0
    for i in range(len(df) - 1):
        if pd.notna(signals[i]['confidence']):
            actual_dir = 1 if df['close'].iloc[i+1] > df['close'].iloc[i] else -1
            pred_dir = 1 if signals[i]['signal'] == 'long' else (-1 if signals[i]['signal'] == 'short' else 0)
            if pred_dir != 0 and actual_dir == pred_dir:
                correct_dirs += 1
            if pred_dir != 0:
                dir_total += 1

    dir_acc = correct_dirs / dir_total * 100 if dir_total > 0 else 50

    # MAE（用持仓期间预测价格与实际价格的偏差均值）
    maes = []
    for i in range(len(df) - 1):
        if signals[i]['signal'] != 'neutral':
            pred_next = df['close'].iloc[i] * (1 + (0.01 if signals[i]['signal'] == 'long' else -0.01))
            actual_next = df['close'].iloc[i + 1]
            maes.append(abs(pred_next - actual_next))

    mae = np.mean(maes) if maes else 0

    final_equity = equity_curve[-1]['strategy'] if equity_curve else initial_capital
    final_benchmark = equity_curve[-1]['benchmark'] if equity_curve else initial_capital

    return {
        'equity_curve': equity_curve,
        'trades': trades,
        'metrics': {
            'sharpe_ratio': round(sharpe, 2),
            'win_rate': round(win_rate * 100, 1),
            'total_pnl': round(total_pnl, 2),
            'avg_pnl_per_trade': round(avg_pnl, 2),
            'mae': round(mae, 2),
            'directional_accuracy': round(dir_acc, 1),
            'total_return': round((final_equity / initial_capital - 1) * 100, 2),
            'benchmark_return': round((final_benchmark / initial_capital - 1) * 100, 2),
            'max_drawdown': round(min([e['strategy'] for e in equity_curve]) / max([e['strategy'] for e in equity_curve] if [e['strategy'] for e in equity_curve] else [1]) - 1, 2) * 100 if equity_curve else 0,
            'total_trades': total_trades,
            'wins': wins,
            'losses': losses
        }
    }

# ─── 预测数据生成（用于展示预测 vs 实际）─────────────────────────────────────

def generate_prediction_data(df: pd.DataFrame, signals: list, pred_len: int = 30) -> list:
    """生成模拟的 OHLCV 预测数据 + 实际数据（最近 N 个周期）"""
    n = min(pred_len, len(df))
    result = []
    for i in range(len(df) - n, len(df)):
        row = df.iloc[i]
        sig = signals[i]
        # 预测值：简单用当日收盘 ± 小幅波动模拟
        base = row['close']
        vol = (row['high'] - row['low']) / base if base > 0 else 0.01
        pred_close = base * (1 + (0.005 if sig['signal'] == 'long' else -0.005))
        result.append({
            't': row['date'],
            'pred_c': round(pred_close, 2),
            'act_c': round(row['close'], 2),
            'signal': sig['signal'],
            'confidence': sig['confidence']
        })
    return result

# ─── 新浪 K 线数据拉取 ────────────────────────────────────────────────────────

def fetch_sina_kline(symbol: str, datalen: int = 300) -> pd.DataFrame:
    """
    通过新浪财经 API 拉取日K数据（无代理环境可用）。
    symbol: 新浪格式，如 'sz000858'、'sh600519'
    返回 DataFrame，含 date/open/high/low/close/volume 列
    """
    # 判断交易所前缀
    code_clean = symbol.replace('.', '').replace('sh', '').replace('sz', '')
    if code_clean.startswith('6'):
        sina_sym = f'sh{code_clean}'
    else:
        sina_sym = f'sz{code_clean}'

    url = 'https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData'
    params = {'symbol': sina_sym, 'scale': '240', 'ma': '5', 'datalen': str(datalen)}
    headers = {'Referer': 'https://finance.sina.com.cn', 'User-Agent': 'Mozilla/5.0'}

    import requests as _req
    r = _req.get(url, params=params, timeout=15, headers=headers)
    rows = r.json()

    df = pd.DataFrame(rows)
    df = df.rename(columns={
        'day': 'date', 'open': 'open', 'high': 'high',
        'low': 'low', 'close': 'close', 'volume': 'volume'
    })
    for col in ['open', 'high', 'low', 'close', 'volume']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df = df.dropna(subset=['close'])
    df = df.sort_values('date').reset_index(drop=True)
    return df, sina_sym

# ─── 主程序 ─────────────────────────────────────────────────────────────────

def run_kronos(
    stock_code: str,
    start_date: str,
    end_date: str,
    lookback: int = 20,
    temperature: float = 0.7,
    pred_len: int = 30
) -> dict:
    """
    入口函数。
    stock_code: A股代码，如 '000858'、'600519'、'sz.000858'、'sh600519'
    数据源：新浪财经日K线（约300个交易日）
    """
    # 规范化代码
    code_raw = stock_code.replace('.', '').lower()
    for prefix in ['sh', 'sz']:
        code_raw = code_raw.replace(prefix, '')

    print(f"  正在拉取 {stock_code} ({start_date} ~ {end_date}) ...", file=sys.stderr)
    df, asset_display = fetch_sina_kline(code_raw, datalen=300)

    # 按日期截取
    df = df[(df['date'] >= start_date) & (df['date'] <= end_date)].copy()
    df = df.reset_index(drop=True)

    if len(df) < lookback + 5:
        raise ValueError(f"数据不足：仅 {len(df)} 条（需 ≥ {lookback + 5} 条）。请缩短日期范围。")

    # 生成信号
    signals = generate_signals(df, lookback=lookback, temperature=temperature)

    # 回测
    bt_result = backtest(df, signals)

    # 预测数据
    pred_data = generate_prediction_data(df, signals, pred_len=pred_len)

    # 信号时间轴（简化：取关键信号点）
    signal_timeline = []
    for i, sig in enumerate(signals):
        if sig['signal'] != 'neutral':
            signal_timeline.append({
                'time': df['date'].iloc[i],
                'signal': sig['signal'],
                'confidence': sig['confidence'],
                'price': sig['price'],
                'reason': sig['reason']
            })

    return {
        'meta': {
            'name': 'Kronos 模型预测回测',
            'description': '均值回归 + 动量信号融合策略 | AKShare A股日线数据',
            'last_updated': datetime.now().strftime('%Y-%m-%d'),
            'asset': asset_display,
            'start_date': start_date,
            'end_date': end_date,
            'lookback': lookback,
            'pred_len': pred_len,
            'temperature': temperature
        },
        'prediction': {
            'start': df['date'].iloc[-pred_len] if len(df) >= pred_len else df['date'].iloc[0],
            'end': df['date'].iloc[-1],
            'timeframe': '1d',
            'last_input_close': round(df['close'].iloc[-1], 2),
            'last_input_high': round(df['high'].iloc[-1], 2),
            'last_input_low': round(df['low'].iloc[-1], 2)
        },
        'metrics': bt_result['metrics'],
        'equity_curve': bt_result['equity_curve'],
        'ohlcv': pred_data,
        'signals': signal_timeline[:50],  # 最多50条
        'trades': bt_result['trades']
    }

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Kronos 回测引擎')
    parser.add_argument('--stock', '-s', required=True, help='股票代码，如 sz.000858')
    parser.add_argument('--start', required=True, help='开始日期 YYYY-MM-DD')
    parser.add_argument('--end', required=True, help='结束日期 YYYY-MM-DD')
    parser.add_argument('--lookback', '-l', type=int, default=20, help='布林带周期')
    parser.add_argument('--temperature', '-t', type=float, default=0.7, help='温度参数 0-1')
    parser.add_argument('--pred_len', '-p', type=int, default=30, help='预测展示长度')
    parser.add_argument('--output', '-o', default='data/kronos-result.json', help='输出文件路径')

    args = parser.parse_args()

    result = run_kronos(
        stock_code=args.stock,
        start_date=args.start,
        end_date=args.end,
        lookback=args.lookback,
        temperature=args.temperature,
        pred_len=args.pred_len
    )

    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"回测完成：{args.output}")
    m = result['metrics']
    print(f"  策略收益率: {m['total_return']}%  |  基准收益率: {m['benchmark_return']}%")
    print(f"  夏普比率: {m['sharpe_ratio']}  |  胜率: {m['win_rate']}%  |  方向准确率: {m['directional_accuracy']}%")
    print(f"  总交易次数: {m['total_trades']}  |  盈亏比: {m['wins']}/{m['losses']}")
