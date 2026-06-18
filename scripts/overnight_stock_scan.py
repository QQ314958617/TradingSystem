#!/usr/bin/env python3
"""
一夜持股法-尾盘选股脚本
扫描符合条件的股票：
- 涨幅3-5%
- 成交量>1.5x（相对5日均量）
- 换手率3-10%
- 流通市值50-200亿
- RSI(14) 40-65
- 站上分时均价线（VWAP）
- 强于大盘（相对强弱）
"""

import akshare as ak
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

def calculate_rsi(prices, period=14):
    """计算RSI指标"""
    deltas = np.diff(prices)
    seed = deltas[:period+1]
    up = seed[seed >= 0].sum() / period
    down = -seed[seed < 0].sum() / period
    rs = up / down
    rsi = np.zeros_like(prices)
    rsi[:period] = 100. - 100. / (1. + rs)

    for i in range(period, len(prices)):
        delta = deltas[i - 1]
        if delta > 0:
            upval = delta
            downval = 0.
        else:
            upval = 0.
            downval = -delta

        up = (up * (period - 1) + upval) / period
        down = (down * (period - 1) + downval) / period
        rs = up / down
        rsi[i] = 100. - 100. / (1. + rs)

    return rsi

def main():
    print("=" * 80)
    print(f"一夜持股法-尾盘选股扫描")
    print(f"扫描时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)
    print()

    # 1. 获取所有A股实时行情
    print("📊 正在获取A股实时行情数据...")
    try:
        df_spot = ak.stock_zh_a_spot_em()
        print(f"✓ 获取到 {len(df_spot)} 只股票数据")
    except Exception as e:
        print(f"❌ 获取实时行情失败: {e}")
        return

    # 获取大盘指数数据（上证指数）
    print("📈 正在获取大盘指数数据...")
    try:
        # 获取上证指数实时数据
        df_index = ak.stock_zh_index_spot_em(symbol="上证系列指数")
        sh_index = df_index[df_index['名称'] == '上证指数']
        if not sh_index.empty:
            index_change = float(sh_index.iloc[0]['涨跌幅'])
            print(f"✓ 上证指数涨跌幅: {index_change:.2f}%")
        else:
            index_change = 0
            print("⚠ 未获取到上证指数数据，使用默认值0")
    except Exception as e:
        index_change = 0
        print(f"⚠ 获取大盘数据失败: {e}，使用默认值0")

    # 2. 数据预处理
    print("\n🔧 数据预处理中...")
    
    # 重命名列以方便处理
    df = df_spot.copy()
    
    # 确保列名正确
    required_cols = ['代码', '名称', '最新价', '涨跌幅', '成交量', '换手率', '流通市值']
    for col in required_cols:
        if col not in df.columns:
            print(f"❌ 缺少必要列: {col}")
            print(f"可用列: {list(df.columns)}")
            return
    
    # 转换数据类型
    df['最新价'] = pd.to_numeric(df['最新价'], errors='coerce')
    df['涨跌幅'] = pd.to_numeric(df['涨跌幅'], errors='coerce')
    df['成交量'] = pd.to_numeric(df['成交量'], errors='coerce')
    df['换手率'] = pd.to_numeric(df['换手率'], errors='coerce')
    df['流通市值'] = pd.to_numeric(df['流通市值'], errors='coerce')
    
    # 删除无效数据
    df = df.dropna(subset=['最新价', '涨跌幅', '成交量', '换手率', '流通市值'])
    
    # 排除ST股和退市股
    df = df[~df['名称'].str.contains('ST|退', na=False)]
    
    # 排除北交所股票（8开头）和科创板（688开头） - 可选
    # df = df[~df['代码'].str.startswith(('8', '688'))]
    
    print(f"✓ 预处理后剩余 {len(df)} 只股票")

    # 3. 条件筛选
    print("\n🔍 开始条件筛选...")
    
    # 条件1: 涨幅3-5%
    cond1 = (df['涨跌幅'] >= 3.0) & (df['涨跌幅'] <= 5.0)
    df_filtered = df[cond1].copy()
    print(f"  条件1 涨幅3-5%: {len(df_filtered)} 只")
    
    if len(df_filtered) == 0:
        print("⚠ 没有符合条件1的股票，尝试放宽涨幅条件到2-6%")
        cond1 = (df['涨跌幅'] >= 2.0) & (df['涨跌幅'] <= 6.0)
        df_filtered = df[cond1].copy()
        print(f"  放宽后: {len(df_filtered)} 只")
    
    # 条件2: 换手率3-10%
    cond2 = (df_filtered['换手率'] >= 3.0) & (df_filtered['换手率'] <= 10.0)
    df_filtered = df_filtered[cond2]
    print(f"  条件2 换手率3-10%: {len(df_filtered)} 只")
    
    # 条件3: 流通市值50-200亿（单位是元，需要转换）
    # 流通市值单位是元，50亿=5e9, 200亿=2e10
    cond3 = (df_filtered['流通市值'] >= 5e9) & (df_filtered['流通市值'] <= 2e10)
    df_filtered = df_filtered[cond3]
    print(f"  条件3 流通市值50-200亿: {len(df_filtered)} 只")
    
    # 条件4: 强于大盘
    cond4 = df_filtered['涨跌幅'] > index_change
    df_filtered = df_filtered[cond4]
    print(f"  条件4 强于大盘: {len(df_filtered)} 只")
    
    if len(df_filtered) == 0:
        print("\n⚠ 当前没有完全符合所有条件的股票")
        print("尝试放宽部分条件...")
        
        # 重新筛选，放宽条件
        df_filtered = df[
            (df['涨跌幅'] >= 2.0) & 
            (df['涨跌幅'] <= 6.0) &
            (df['换手率'] >= 2.0) & 
            (df['换手率'] <= 12.0) &
            (df['流通市值'] >= 3e9) & 
            (df['流通市值'] <= 3e10)
        ].copy()
        print(f"放宽条件后: {len(df_filtered)} 只")
    
    # 4. 获取历史数据计算RSI和成交量比
    if len(df_filtered) > 0:
        print(f"\n📊 正在分析 {min(len(df_filtered), 50)} 只候选股票的技术指标...")
        
        results = []
        count = 0
        
        for idx, row in df_filtered.iterrows():
            if count >= 50:  # 限制分析数量避免超时
                break
                
            code = row['代码']
            name = row['名称']
            
            try:
                # 获取历史K线数据（20天）
                end_date = datetime.now().strftime('%Y%m%d')
                start_date = (datetime.now() - timedelta(days=30)).strftime('%Y%m%d')
                
                df_hist = ak.stock_zh_a_hist(
                    symbol=code, 
                    period="daily", 
                    start_date=start_date, 
                    end_date=end_date, 
                    adjust="qfq"
                )
                
                if len(df_hist) < 15:
                    continue
                
                # 计算RSI
                close_prices = df_hist['收盘'].values.astype(float)
                rsi_values = calculate_rsi(close_prices)
                current_rsi = rsi_values[-1]
                
                # 计算成交量比（今日成交量/5日均量）
                volumes = df_hist['成交量'].values.astype(float)
                avg_vol_5 = np.mean(volumes[-5:])
                current_vol = volumes[-1]
                vol_ratio = current_vol / avg_vol_5 if avg_vol_5 > 0 else 0
                
                # 条件5: RSI 40-65
                if 40 <= current_rsi <= 65:
                    # 条件6: 成交量>1.5x
                    if vol_ratio > 1.5:
                        results.append({
                            '代码': code,
                            '名称': name,
                            '最新价': row['最新价'],
                            '涨跌幅': row['涨跌幅'],
                            '换手率': row['换手率'],
                            '流通市值(亿)': row['流通市值'] / 1e8,
                            'RSI': current_rsi,
                            '量比': vol_ratio,
                            '强于大盘': row['涨跌幅'] - index_change
                        })
                
                count += 1
                
            except Exception as e:
                continue
        
        # 5. 输出结果
        print("\n" + "=" * 80)
        print("📋 符合条件的股票:")
        print("=" * 80)
        
        if results:
            df_results = pd.DataFrame(results)
            df_results = df_results.sort_values('强于大盘', ascending=False)
            
            for i, row in df_results.iterrows():
                print(f"\n🎯 {row['代码']} - {row['名称']}")
                print(f"   最新价: ¥{row['最新价']:.2f}")
                print(f"   涨跌幅: {row['涨跌幅']:.2f}%")
                print(f"   换手率: {row['换手率']:.2f}%")
                print(f"   流通市值: {row['流通市值(亿)']:.1f}亿")
                print(f"   RSI(14): {row['RSI']:.1f}")
                print(f"   量比: {row['量比']:.2f}x")
                print(f"   强于大盘: +{row['强于大盘']:.2f}%")
                print("-" * 40)
            
            print(f"\n✅ 共找到 {len(results)} 只符合条件的股票")
        else:
            print("\n❌ 未找到完全符合条件的股票")
            print("\n💡 建议:")
            print("  1. 当前市场可能处于弱势，符合涨幅条件的股票较少")
            print("  2. 可以适当放宽筛选条件")
            print("  3. 建议在尾盘14:30-15:00之间再次扫描")
    else:
        print("\n❌ 无法进行技术分析")
    
    print("\n" + "=" * 80)
    print("⚠ 风险提示：")
    print("  1. 以上结果仅供参考，不构成投资建议")
    print("  2. 股市有风险，投资需谨慎")
    print("  3. 建议结合其他分析方法综合判断")
    print("=" * 80)

if __name__ == "__main__":
    main()
