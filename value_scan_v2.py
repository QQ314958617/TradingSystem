#!/usr/bin/env python3
"""
价值投资扫描 v2 - 扩大数据范围
筛选 PE < 15 且 ROE > 15% 的价值股
"""

import requests
import json
from datetime import datetime

print("=" * 60)
print(f"🥚 蛋蛋基金 - 价值投资扫描")
print(f"📅 扫描时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
print("=" * 60)

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Referer': 'https://data.eastmoney.com/',
}

# 获取全部 A 股数据（分页获取）
all_stocks = []

print("\n📊 正在从东方财富获取全量 A 股数据...")

for page in range(1, 20):  # 获取前20页，约2000只股票
    try:
        url = "https://push2.eastmoney.com/api/qt/clist/get"
        params = {
            'pn': str(page),
            'pz': '100',
            'po': '1',
            'np': '1',
            'ut': 'bd1d9ddb04089700cf9c27f6f7426281',
            'fltt': '2',
            'invt': '2',
            'fid': 'f37',  # 按 ROE 排序
            'fs': 'm:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23',  # A股
            'fields': 'f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f13,f14,f15,f16,f17,f18,f20,f21,f23,f24,f25,f26,f37,f100,f152',
        }
        resp = requests.get(url, params=params, headers=headers, timeout=30)
        data = resp.json()
        
        if data.get('data') and data['data'].get('diff'):
            stocks = data['data']['diff']
            all_stocks.extend(stocks)
            print(f"  第{page}页: 获取 {len(stocks)} 只")
            
            # 如果返回的数据少于100，说明已经是最后一页
            if len(stocks) < 100:
                break
        else:
            break
    except Exception as e:
        print(f"  第{page}页失败: {e}")
        break

print(f"\n✅ 共获取 {len(all_stocks)} 只 A 股数据")

# 筛选 PE < 15 且 ROE > 15%
filtered = []
for s in all_stocks:
    pe = s.get('f9')  # 市盈率(动)
    roe = s.get('f37')  # ROE
    name = s.get('f14', '')
    code = s.get('f12', '')
    price = s.get('f2')
    pb = s.get('f23')
    market_cap = s.get('f20')
    change_pct = s.get('f3')
    change_60d = s.get('f24')  # 60日涨跌幅
    industry = s.get('f100', '')
    
    # 排除 ST、退市、B股
    if 'ST' in name or '退' in name or 'B' in name:
        continue
        
    # 筛选条件
    if pe and roe and price:
        try:
            pe = float(pe)
            roe = float(roe)
            price = float(price)
            if 0 < pe < 15 and roe > 15 and price > 0:
                filtered.append({
                    'code': code,
                    'name': name,
                    'price': price,
                    'pe': pe,
                    'roe': roe,
                    'pb': float(pb) if pb else 0,
                    'market_cap': float(market_cap) / 1e8 if market_cap else 0,
                    'change_pct': float(change_pct) if change_pct else 0,
                    'change_60d': float(change_60d) if change_60d else 0,
                    'industry': industry if industry else '未知',
                })
        except (ValueError, TypeError):
            continue

# 按 ROE 降序排序
filtered.sort(key=lambda x: x['roe'], reverse=True)

print(f"\n🔍 筛选结果: {len(filtered)} 只股票符合 PE<15 且 ROE>15%")

if filtered:
    print("\n" + "=" * 70)
    print("🏆 价值投资精选 - 巴菲特选股器")
    print("=" * 70)
    print(f"{'序号':>4} {'代码':<8} {'名称':<10} {'股价':>8} {'PE':>8} {'ROE':>8} {'PB':>6} {'市值':>8} {'行业':<10}")
    print("-" * 70)
    
    for i, s in enumerate(filtered[:50], 1):
        print(f"{i:4d} {s['code']:<8} {s['name']:<10} {s['price']:8.2f} {s['pe']:8.2f} {s['roe']:8.2f}% {s['pb']:6.2f} {s['market_cap']:7.0f}亿 {s['industry']:<10}")
    
    # 重点推荐（PE<10 且 ROE>20%）
    top_picks = [s for s in filtered if s['pe'] < 10 and s['roe'] > 20]
    
    if top_picks:
        print("\n" + "=" * 70)
        print("⭐ 重点推荐 - PE<10 且 ROE>20%")
        print("=" * 70)
        for s in top_picks:
            print(f"\n🏢 {s['name']} ({s['code']})")
            print(f"   💰 股价: ¥{s['price']:.2f}  |  📊 PE: {s['pe']:.2f}  |  📈 ROE: {s['roe']:.2f}%")
            print(f"   📋 PB: {s['pb']:.2f}  |  🏢 市值: {s['market_cap']:.0f}亿  |  🏭 行业: {s['industry']}")
            
            # 估值评级
            if s['pe'] < 8:
                print(f"   🎯 估值: 极度低估 ⭐⭐⭐⭐⭐")
            elif s['pe'] < 10:
                print(f"   🎯 估值: 明显低估 ⭐⭐⭐⭐")
            
            # ROE 评级
            if s['roe'] > 25:
                print(f"   💪 盈利能力: 极强 ⭐⭐⭐⭐⭐")
            elif s['roe'] > 20:
                print(f"   💪 盈利能力: 优秀 ⭐⭐⭐⭐")
    
    # 行业分布统计
    print("\n" + "=" * 70)
    print("📊 行业分布统计")
    print("=" * 70)
    industry_count = {}
    for s in filtered:
        ind = s['industry']
        industry_count[ind] = industry_count.get(ind, 0) + 1
    
    sorted_industries = sorted(industry_count.items(), key=lambda x: x[1], reverse=True)
    for ind, count in sorted_industries[:10]:
        print(f"  {ind}: {count} 只")
    
    # 保存结果
    import csv
    output_file = '/root/.openclaw/workspace/value_stocks_result.csv'
    with open(output_file, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=filtered[0].keys())
        writer.writeheader()
        writer.writerows(filtered)
    print(f"\n💾 完整结果已保存: {output_file}")
    
else:
    print("\n❌ 未找到符合条件的股票")
    print("可能原因: 1) 数据获取不完整 2) 当前市场环境符合标准的股票较少")

print("\n" + "=" * 70)
print("📝 风险提示: 以上分析仅供参考，不构成投资建议。")
print("   投资有风险，入市需谨慎。- 蛋蛋基金 🥚")
print("=" * 70)
