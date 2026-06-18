#!/usr/bin/env python3
"""
趋势跟踪扫描器 (Baostock版本)
寻找均线金叉+放量突破的中短线机会
目标：持股1-2周
"""

import baostock as bs
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

def login():
    """登录baostock"""
    lg = bs.login()
    if lg.error_code != '0':
        print(f"登录失败: {lg.error_msg}")
        return False
    return True

def logout():
    """登出baostock"""
    bs.logout()

def get_stock_list():
    """获取A股股票列表"""
    try:
        # 获取沪深A股列表
        rs = bs.query_stock_basic()
        stocks = []
        while rs.next():
            row = rs.get_row_data()
            # 过滤：A股、上市状态正常
            if row[0].startswith(('sh.6', 'sz.0', 'sz.3')) and row[4] == '1':
                stocks.append({
                    'code': row[0],
                    'name': row[1],
                    'ipoDate': row[2],
                    'outDate': row[3],
                    'status': row[4]
                })
        return pd.DataFrame(stocks)
    except Exception as e:
        print(f"获取股票列表失败: {e}")
        return pd.DataFrame()

def get_history_data(code, start_date, end_date):
    """获取历史K线数据"""
    try:
        rs = bs.query_history_k_data_plus(
            code,
            "date,open,high,low,close,volume,amount,turn",
            start_date=start_date,
            end_date=end_date,
            frequency="d",
            adjustflag="2"  # 前复权
        )
        data_list = []
        while rs.next():
            data_list.append(rs.get_row_data())
        
        if not data_list:
            return pd.DataFrame()
        
        df = pd.DataFrame(data_list, columns=rs.fields)
        # 转换数据类型
        for col in ['open', 'high', 'low', 'close', 'volume', 'amount', 'turn']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date').reset_index(drop=True)
        return df
    except Exception as e:
        return pd.DataFrame()

def calculate_ma(df, periods=[5, 10, 20, 60]):
    """计算均线"""
    for period in periods:
        df[f'MA{period}'] = df['close'].rolling(window=period).mean()
    return df

def detect_golden_cross(df, short_period=5, long_period=20):
    """检测均线金叉"""
    if len(df) < long_period + 2:
        return False
    
    ma_short_prev = df[f'MA{short_period}'].iloc[-2]
    ma_short_curr = df[f'MA{short_period}'].iloc[-1]
    ma_long_prev = df[f'MA{long_period}'].iloc[-2]
    ma_long_curr = df[f'MA{long_period}'].iloc[-1]
    
    # 金叉：短期均线从下方穿越长期均线
    if pd.notna(ma_short_prev) and pd.notna(ma_long_prev):
        if ma_short_prev <= ma_long_prev and ma_short_curr > ma_long_curr:
            return True
    return False

def detect_volume_breakout(df, volume_ratio=2.0):
    """检测放量突破"""
    if len(df) < 20:
        return False
    
    avg_volume = df['volume'].iloc[-21:-1].mean()
    current_volume = df['volume'].iloc[-1]
    
    if pd.notna(avg_volume) and avg_volume > 0:
        if current_volume > avg_volume * volume_ratio:
            return True
    return False

def detect_price_breakout(df, lookback=20):
    """检测价格突破"""
    if len(df) < lookback + 1:
        return False
    
    recent_high = df['high'].iloc[-(lookback+1):-1].max()
    current_close = df['close'].iloc[-1]
    
    if pd.notna(recent_high) and current_close > recent_high:
        return True
    return False

def analyze_stock(code, name):
    """分析单只股票"""
    try:
        # 获取最近120天数据
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=180)).strftime('%Y-%m-%d')
        
        df = get_history_data(code, start_date, end_date)
        
        if len(df) < 30:
            return None
        
        # 计算均线
        df = calculate_ma(df)
        
        # 检测信号
        golden_cross = detect_golden_cross(df, short_period=5, long_period=20)
        volume_breakout = detect_volume_breakout(df, volume_ratio=2.0)
        price_breakout = detect_price_breakout(df, lookback=20)
        
        # 计算当前价格和涨跌幅
        current_price = df['close'].iloc[-1]
        prev_price = df['close'].iloc[-2] if len(df) > 1 else current_price
        change_pct = ((current_price - prev_price) / prev_price) * 100 if prev_price > 0 else 0
        
        # 计算均线排列
        ma5 = df['MA5'].iloc[-1]
        ma10 = df['MA10'].iloc[-1]
        ma20 = df['MA20'].iloc[-1]
        
        bullish_alignment = False
        if pd.notna(ma5) and pd.notna(ma10) and pd.notna(ma20):
            bullish_alignment = ma5 > ma10 > ma20
        
        # 计算成交量比
        avg_volume = df['volume'].iloc[-21:-1].mean()
        current_volume = df['volume'].iloc[-1]
        volume_ratio = current_volume / avg_volume if pd.notna(avg_volume) and avg_volume > 0 else 0
        
        # 计算换手率
        turnover = df['turn'].iloc[-1] if 'turn' in df.columns else 0
        
        # 综合评分
        score = 0
        if golden_cross:
            score += 30
        if volume_breakout:
            score += 25
        if price_breakout:
            score += 25
        if bullish_alignment:
            score += 20
        
        # 过滤条件：涨幅2%-7%，换手率适中
        if change_pct < 1.5 or change_pct > 8.0:
            return None
        
        if turnover < 0.5 or turnover > 15:  # 换手率过低或过高
            return None
        
        return {
            'code': code,
            'name': name,
            'current_price': current_price,
            'change_pct': change_pct,
            'golden_cross': golden_cross,
            'volume_breakout': volume_breakout,
            'price_breakout': price_breakout,
            'bullish_alignment': bullish_alignment,
            'volume_ratio': volume_ratio,
            'turnover': turnover,
            'ma5': ma5,
            'ma10': ma10,
            'ma20': ma20,
            'score': score
        }
    except Exception as e:
        return None

def main():
    """主扫描函数"""
    print("🔍 开始趋势跟踪扫描 (Baostock)...")
    print("=" * 60)
    
    # 登录
    if not login():
        return
    
    # 获取股票列表
    stock_list = get_stock_list()
    if stock_list.empty:
        print("❌ 获取股票列表失败")
        logout()
        return
    
    print(f"📊 共获取 {len(stock_list)} 只A股")
    
    # 随机采样200只股票进行分析（全量扫描太慢）
    sample_size = min(200, len(stock_list))
    sampled_stocks = stock_list.sample(n=sample_size, random_state=42)
    
    print(f"📈 随机采样 {sample_size} 只股票进行分析...")
    
    # 分析股票
    results = []
    for idx, row in sampled_stocks.iterrows():
        code = row['code']
        name = row['name']
        
        result = analyze_stock(code, name)
        if result and result['score'] >= 40:  # 评分40分以上
            results.append(result)
        
        # 进度显示
        if (idx + 1) % 20 == 0:
            print(f"   已分析 {idx + 1}/{sample_size} 只...")
    
    # 登出
    logout()
    
    # 按评分排序
    results.sort(key=lambda x: x['score'], reverse=True)
    
    # 输出结果
    print("\n" + "=" * 60)
    print("🎯 趋势跟踪扫描结果")
    print("=" * 60)
    
    if not results:
        print("❌ 未发现符合条件的股票")
        print("\n💡 可能原因：")
        print("  1. 当前市场缺乏明确趋势")
        print("  2. 采样数量有限，可能遗漏机会")
        print("  3. 筛选条件较严格")
        return
    
    # 输出Top 15
    top_results = results[:15]
    
    for i, stock in enumerate(top_results, 1):
        print(f"\n#{i} {stock['name']} ({stock['code']})")
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
        print(f"   📦 量比: {stock['volume_ratio']:.2f} | 换手率: {stock['turnover']:.2f}%")
        print(f"   ⭐ 综合评分: {stock['score']}")
    
    # 统计
    print("\n" + "=" * 60)
    print("📊 统计摘要")
    print("=" * 60)
    
    golden_cross_count = sum(1 for r in results if r['golden_cross'])
    volume_breakout_count = sum(1 for r in results if r['volume_breakout'])
    price_breakout_count = sum(1 for r in results if r['price_breakout'])
    bullish_alignment_count = sum(1 for r in results if r['bullish_alignment'])
    
    print(f"扫描股票: {sample_size} 只（随机采样）")
    print(f"符合条件: {len(results)} 只")
    print(f"金叉信号: {golden_cross_count} 只")
    print(f"放量信号: {volume_breakout_count} 只")
    print(f"突破信号: {price_breakout_count} 只")
    print(f"多头排列: {bullish_alignment_count} 只")
    
    # 输出CSV
    if results:
        df_results = pd.DataFrame(results)
        csv_path = '/root/.openclaw/workspace/data/trend_scan_results.csv'
        df_results.to_csv(csv_path, index=False, encoding='utf-8-sig')
        print(f"\n💾 结果已保存至: {csv_path}")
    
    # 操作建议
    print("\n" + "=" * 60)
    print("💡 操作建议")
    print("=" * 60)
    print("1. 关注评分≥60的股票，信号更明确")
    print("2. 金叉+放量组合信号成功率较高")
    print("3. 建议持股1-2周，目标收益5-10%")
    print("4. 设置止损位：跌破MA20或买入价-5%")
    print("5. 注意大盘环境，弱势行情谨慎操作")
    
    return results

if __name__ == "__main__":
    main()
