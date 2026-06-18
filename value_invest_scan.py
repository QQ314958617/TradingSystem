#!/usr/bin/env python3
"""
价值投资扫描 - 巴菲特选股器
筛选 PE < 15 且 ROE > 15% 的价值股
"""

import akshare as ak
import pandas as pd
from datetime import datetime

print("=" * 60)
print(f"🥚 蛋蛋基金 - 价值投资扫描")
print(f"📅 扫描时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
print("=" * 60)

# 获取 A 股实时行情（含 PE 数据）
print("\n📊 正在获取 A 股行情数据...")
try:
    df = ak.stock_zh_a_spot_em()
    print(f"✅ 获取到 {len(df)} 只股票数据")
except Exception as e:
    print(f"❌ 获取行情失败: {e}")
    exit(1)

# 查看列名
print(f"\n可用列: {list(df.columns)}")

# 重命名列以便处理
col_map = {
    '代码': 'code',
    '名称': 'name',
    '最新价': 'price',
    '涨跌幅': 'change_pct',
    '市盈率-动态': 'pe',
    '市净率': 'pb',
    '总市值': 'market_cap',
    '流通市值': 'float_cap',
    '60日涨跌幅': 'change_60d',
}

# 选择需要的列
available_cols = {k: v for k, v in col_map.items() if k in df.columns}
df_selected = df[list(available_cols.keys())].copy()
df_selected.columns = list(available_cols.values())

# 数据清洗
print("\n🔧 数据清洗中...")

# 转换数值类型
for col in ['price', 'change_pct', 'pe', 'pb', 'market_cap', 'float_cap', 'change_60d']:
    if col in df_selected.columns:
        df_selected[col] = pd.to_numeric(df_selected[col], errors='coerce')

# 过滤掉 ST 股票
df_selected = df_selected[~df_selected['name'].str.contains('ST|退市', na=False)]

# 过滤掉停牌（价格为0或NaN的）
df_selected = df_selected[df_selected['price'] > 0]

print(f"✅ 清洗后剩余 {len(df_selected)} 只股票")

# ==================== 筛选条件 ====================
print("\n" + "=" * 60)
print("🔍 巴菲特选股条件: PE < 15 且 ROE > 15%")
print("=" * 60)

# 条件1: PE < 15（排除负值）
pe_filter = (df_selected['pe'] > 0) & (df_selected['pe'] < 15)

# 注：akshare 的实时行情可能不直接包含 ROE
# 我们先筛选出 PE < 15 的股票，再获取其财务数据验证 ROE
value_stocks = df_selected[pe_filter].copy()

print(f"\n📊 符合 PE < 15 条件的股票: {len(value_stocks)} 只")

# 按 PE 排序，取前50只进行深度分析
value_stocks = value_stocks.sort_values('pe').head(50)

print("\n🎯 PE 最低的前50只股票:")
print("-" * 60)
for idx, row in value_stocks.iterrows():
    cap_yi = row['market_cap'] / 1e8 if pd.notna(row['market_cap']) else 0
    print(f"  {row['code']} {row['name']:<8} PE={row['pe']:.2f}  市值={cap_yi:.0f}亿")

# ==================== 获取财务数据验证 ROE ====================
print("\n" + "=" * 60)
print("📈 正在验证 ROE 数据（可能需要一些时间）...")
print("=" * 60)

roe_results = []
failed_count = 0

for idx, row in value_stocks.iterrows():
    code = row['code']
    try:
        # 获取财务指标
        fin = ak.stock_financial_analysis_indicator(symbol=code)
        if fin is not None and len(fin) > 0:
            # 取最新一期的 ROE
            roe_col = None
            for col in fin.columns:
                if '净资产收益率' in col or 'roe' in col.lower():
                    roe_col = col
                    break
            
            if roe_col:
                latest_roe = pd.to_numeric(fin[roe_col].iloc[0], errors='coerce')
                if pd.notna(latest_roe) and latest_roe > 15:
                    roe_results.append({
                        'code': code,
                        'name': row['name'],
                        'price': row['price'],
                        'pe': row['pe'],
                        'roe': latest_roe,
                        'pb': row.get('pb', 0),
                        'market_cap': row.get('market_cap', 0),
                        'change_60d': row.get('change_60d', 0)
                    })
    except Exception as e:
        failed_count += 1
        continue

print(f"\n✅ ROE 验证完成，失败 {failed_count} 只")

# ==================== 输出结果 ====================
if roe_results:
    result_df = pd.DataFrame(roe_results)
    result_df = result_df.sort_values('roe', ascending=False)
    
    print("\n" + "=" * 60)
    print("🏆 价值投资精选 - PE < 15 且 ROE > 15%")
    print("=" * 60)
    print(f"共筛选出 {len(result_df)} 只股票\n")
    
    for idx, row in result_df.iterrows():
        cap_yi = row['market_cap'] / 1e8 if pd.notna(row['market_cap']) else 0
        change_60d = row['change_60d'] if pd.notna(row['change_60d']) else 0
        
        print(f"{'='*50}")
        print(f"  🏢 {row['name']} ({row['code']})")
        print(f"  💰 股价: ¥{row['price']:.2f}")
        print(f"  📊 PE: {row['pe']:.2f} | ROE: {row['roe']:.2f}% | PB: {row['pb']:.2f}")
        print(f"  📈 市值: {cap_yi:.0f}亿 | 60日涨跌: {change_60d:.2f}%")
        
        # 简单评级
        score = 0
        if row['pe'] < 10:
            score += 3
        elif row['pe'] < 12:
            score += 2
        else:
            score += 1
            
        if row['roe'] > 20:
            score += 3
        elif row['roe'] > 18:
            score += 2
        else:
            score += 1
            
        if row['pb'] and row['pb'] < 2:
            score += 1
            
        stars = "⭐" * min(score, 5)
        print(f"  🎯 评级: {stars} ({score}/7)")
        
        # 60日涨跌建议
        if change_60d < -10:
            print(f"  💡 建议: 近60日回调 {change_60d:.1f}%，可关注抄底机会")
        elif change_60d > 20:
            print(f"  ⚠️ 注意: 近60日已上涨 {change_60d:.1f}%，短期追高风险")
        else:
            print(f"  ✅ 趋势: 近60日波动 {change_60d:.1f}%，可择机介入")
    
    # 保存结果
    output_file = '/root/.openclaw/workspace/value_stocks_result.csv'
    result_df.to_csv(output_file, index=False, encoding='utf-8-sig')
    print(f"\n💾 结果已保存到: {output_file}")
    
else:
    print("\n❌ 未找到同时满足 PE<15 且 ROE>15% 的股票")
    print("可能原因:")
    print("1. 当前市场环境下符合标准的股票较少")
    print("2. 需要调整筛选条件")

print("\n" + "=" * 60)
print("📝 风险提示: 以上分析仅供参考，不构成投资建议。")
print("   投资有风险，入市需谨慎。- 蛋蛋基金 🥚")
print("=" * 60)
