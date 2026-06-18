#!/usr/bin/env python3
"""
趋势跟踪扫描器 - 寻找均线金叉+放量突破的中短线机会
目标：持股1-2周的中短线机会
"""

import akshare as ak
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

def get_stock_list():
    """获取A股股票列表"""
    try:
        # 获取实时行情
        df = ak.stock_zh_a_spot_em()
        # 过滤ST股和新股
        df = df[~df['名称'].str.contains('ST|N|C|U', na=False)]
        # 过滤停牌
        df = df[df['成交量'] > 0]
        return df
    except Exception as e:
        print(f"获取股票列表失败: {e}")
        return pd.DataFrame()

def calculate_ma(df, periods=[5, 10, 20, 60]):
    """计算均线"""
    for period in periods:
        df[f'MA{period}'] = df['收盘'].rolling(window=period).mean()
    return df

def detect_golden_cross(df, short_period=5, long_period=20):
    """检测均线金叉"""
    if len(df) < long_period + 2:
        return False
    
    # 获取最近两天的均线值
    ma_short_prev = df[f'MA{short_period}'].iloc[-2]
    ma_short_curr = df[f'MA{short_period}'].iloc[-1]
    ma_long_prev = df[f'MA{long_period}'].iloc[-2]
    ma_long_curr = df[f'MA{long_period}'].iloc[-1]
    
    # 金叉条件：短期均线从下方穿越长期均线
    if ma_short_prev <= ma_long_prev and ma_short_curr > ma_long_curr:
        return True
    return False

def detect_volume_breakout(df, volume_ratio=2.0):
    """检测放量突破"""
    if len(df) < 20:
        return False
    
    # 计算20日平均成交量
    avg_volume = df['成交量'].iloc[-21:-1].mean()
    current_volume = df['成交量'].iloc[-1]
    
    # 放量条件：当日成交量超过20日均量的2倍
    if current_volume > avg_volume * volume_ratio:
        return True
    return False

def detect_price_breakout(df, lookback=20):
    """检测价格突破"""
    if len(df) < lookback + 1:
        return False
    
    # 获取过去lookback天的最高价
    recent_high = df['最高'].iloc[-(lookback+1):-1].max()
    current_close = df['收盘'].iloc[-1]
    
    # 突破条件：收盘价突破近期高点
    if current_close > recent_high:
        return True
    return False

def analyze_stock(symbol, name):
    """分析单只股票"""
    try:
        # 获取历史数据（最近60个交易日）
        end_date = datetime.now().strftime('%Y%m%d')
        start_date = (datetime.now() - timedelta(days=120)).strftime('%Y%m%d')
        
        df = ak.stock_zh_a_hist(symbol=symbol, period="daily", 
                                 start_date=start_date, end_date=end_date, adjust="qfq")
        
        if len(df) < 30:
            return None
        
        # 计算均线
        df = calculate_ma(df)
        
        # 检测信号
        golden_cross = detect_golden_cross(df, short_period=5, long_period=20)
        volume_breakout = detect_volume_breakout(df, volume_ratio=2.0)
        price_breakout = detect_price_breakout(df, lookback=20)
        
        # 计算当前价格和涨跌幅
        current_price = df['收盘'].iloc[-1]
        change_pct = ((df['收盘'].iloc[-1] - df['收盘'].iloc[-2]) / df['收盘'].iloc[-2]) * 100
        
        # 计算均线排列
        ma5 = df['MA5'].iloc[-1]
        ma10 = df['MA10'].iloc[-1]
        ma20 = df['MA20'].iloc[-1]
        
        bullish_alignment = ma5 > ma10 > ma20  # 多头排列
        
        # 计算成交量比
        avg_volume = df['成交量'].iloc[-21:-1].mean()
        current_volume = df['成交量'].iloc[-1]
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0
        
        # 综合评分（0-100）
        score = 0
        if golden_cross:
            score += 30
        if volume_breakout:
            score += 25
        if price_breakout:
            score += 25
        if bullish_alignment:
            score += 20
        
        return {
            'symbol': symbol,
            'name': name,
            'current_price': current_price,
            'change_pct': change_pct,
            'golden_cross': golden_cross,
            'volume_breakout': volume_breakout,
            'price_breakout': price_breakout,
            'bullish_alignment': bullish_alignment,
            'volume_ratio': volume_ratio,
            'ma5': ma5,
            'ma10': ma10,
            'ma20': ma20,
            'score': score
        }
    except Exception as e:
        return None

def main():
    """主扫描函数"""
    print("🔍 开始趋势跟踪扫描...")
    print("=" * 60)
    
    # 获取股票列表
    stock_list = get_stock_list()
    if stock_list.empty:
        print("❌ 获取股票列表失败")
        return
    
    print(f"📊 共获取 {len(stock_list)} 只股票")
    
    # 筛选条件：涨幅在2%-7%之间的股票（排除涨停和下跌）
    filtered_stocks = stock_list[
        (stock_list['涨跌幅'] >= 2.0) & 
        (stock_list['涨跌幅'] <= 7.0) &
        (stock_list['成交额'] > 10000000)  # 成交额大于1000万
    ].copy()
    
    print(f"📈 初步筛选：{len(filtered_stocks)} 只股票符合条件")
    
    # 分析股票
    results = []
    for idx, row in filtered_stocks.iterrows():
        symbol = row['代码']
        name = row['名称']
        
        result = analyze_stock(symbol, name)
        if result and result['score'] >= 50:  # 只保留评分50分以上的
            results.append(result)
    
    # 按评分排序
    results.sort(key=lambda x: x['score'], reverse=True)
    
    # 输出结果
    print("\n" + "=" * 60)
    print("🎯 趋势跟踪扫描结果")
    print("=" * 60)
    
    if not results:
        print("❌ 未发现符合条件的股票")
        return
    
    # 输出Top 20
    top_results = results[:20]
    
    for i, stock in enumerate(top_results, 1):
        print(f"\n#{i} {stock['name']} ({stock['symbol']})")
        print(f"   💰 当前价: {stock['current_price']:.2f} | 涨跌幅: {stock['change_pct']:+.2f}%")
        print(f"   📊 信号: ", end="")
        
        signals = []
        if stock['golden_cross']:
            signals.append("🔴 金叉")
        if stock['volume_breakout']:
            signals.append("🟢 放量")
        if stock['price_breakout']:
            signals.append("🟡 突破")
        if stock['bullish_alignment']:
            signals.append("🔵 多头排列")
        
        print(" | ".join(signals) if signals else "无明显信号")
        
        print(f"   📈 均线: MA5={stock['ma5']:.2f} | MA10={stock['ma10']:.2f} | MA20={stock['ma20']:.2f}")
        print(f"   📦 量比: {stock['volume_ratio']:.2f}")
        print(f"   ⭐ 综合评分: {stock['score']}")
    
    # 统计
    print("\n" + "=" * 60)
    print("📊 统计摘要")
    print("=" * 60)
    
    golden_cross_count = sum(1 for r in results if r['golden_cross'])
    volume_breakout_count = sum(1 for r in results if r['volume_breakout'])
    price_breakout_count = sum(1 for r in results if r['price_breakout'])
    bullish_alignment_count = sum(1 for r in results if r['bullish_alignment'])
    
    print(f"总扫描股票: {len(stock_list)}")
    print(f"初步筛选: {len(filtered_stocks)}")
    print(f"符合条件: {len(results)}")
    print(f"金叉信号: {golden_cross_count} 只")
    print(f"放量信号: {volume_breakout_count} 只")
    print(f"突破信号: {price_breakout_count} 只")
    print(f"多头排列: {bullish_alignment_count} 只")
    
    # 输出CSV文件
    if results:
        df_results = pd.DataFrame(results)
        csv_path = '/root/.openclaw/workspace/data/trend_scan_results.csv'
        df_results.to_csv(csv_path, index=False, encoding='utf-8-sig')
        print(f"\n💾 结果已保存至: {csv_path}")
    
    return results

if __name__ == "__main__":
    main()
