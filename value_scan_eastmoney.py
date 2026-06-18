#!/usr/bin/env python3
"""
价值投资扫描 - 东方财富接口
筛选 PE < 15 且 ROE > 15% 的价值股
"""

import requests
import json
from datetime import datetime

print("=" * 60)
print(f"🥚 蛋蛋基金 - 价值投资扫描")
print(f"📅 扫描时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
print("=" * 60)

# 东方财富选股器 API - 筛选低PE股票
# PE < 15, ROE > 15%, 排除ST
url = "https://datacenter-web.eastmoney.com/api/data/v1/get"

# 构建筛选条件
# FILTER: PE(动)<15, ROE(加权)>15%
filter_str = '(PE_DYN<15)(PE_DYN>0)(ROE_WEIGHT>15)'

params = {
    'sortColumns': 'ROE_WEIGHT',
    'sortTypes': '-1',
    'pageSize': '200',
    'pageNumber': '1',
    'reportName': 'RPT_VALUEDAILY_VALUEDAILY',
    'columns': 'ALL',
    'filter': filter_str,
    'source': 'WEB',
    'client': 'WEB',
}

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Referer': 'https://data.eastmoney.com/',
}

print("\n📊 正在从东方财富获取数据...")

try:
    resp = requests.get(url, params=params, headers=headers, timeout=30)
    data = resp.json()
    
    if data.get('success') and data.get('result') and data['result'].get('data'):
        stocks = data['result']['data']
        print(f"✅ 获取到 {len(stocks)} 只符合条件的股票")
    else:
        print(f"❌ API 返回: {data.get('message', '未知错误')}")
        stocks = []
except Exception as e:
    print(f"❌ 请求失败: {e}")
    stocks = []

if not stocks:
    # 备用方案：直接用另一个API
    print("\n🔄 尝试备用接口...")
    try:
        # 东方财富 A股综合选股
        url2 = "https://push2.eastmoney.com/api/qt/clist/get"
        params2 = {
            'pn': '1',
            'pz': '500',
            'po': '1',
            'np': '1',
            'ut': 'bd1d9ddb04089700cf9c27f6f7426281',
            'fltt': '2',
            'invt': '2',
            'fid': 'f3',
            'fs': 'm:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23',  # A股
            'fields': 'f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f13,f14,f15,f16,f17,f18,f20,f21,f23,f24,f25,f26,f37,f100,f152',
        }
        resp2 = requests.get(url2, params=params2, headers=headers, timeout=30)
        data2 = resp2.json()
        
        if data2.get('data') and data2['data'].get('diff'):
            all_stocks = data2['data']['diff']
            print(f"✅ 获取到 {len(all_stocks)} 只 A 股数据")
            
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
                
                # 排除 ST
                if 'ST' in name or '退' in name:
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
                            })
                    except (ValueError, TypeError):
                        continue
            
            stocks = filtered
            print(f"✅ 筛选出 {len(stocks)} 只 PE<15 且 ROE>15% 的股票")
    except Exception as e:
        print(f"❌ 备用接口也失败: {e}")
        stocks = []

# 输出结果
if stocks:
    print("\n" + "=" * 60)
    print("🏆 价值投资精选 - PE < 15 且 ROE > 15%")
    print("=" * 60)
    
    # 按 ROE 降序排序
    if isinstance(stocks[0], dict) and 'roe' in stocks[0]:
        stocks.sort(key=lambda x: x['roe'], reverse=True)
    
    for i, s in enumerate(stocks[:30], 1):
        code = s.get('code', s.get('SECURITY_CODE', ''))
        name = s.get('name', s.get('SECURITY_NAME_ABBR', ''))
        price = s.get('price', s.get('NEW_PRICE', 0))
        pe = s.get('pe', s.get('PE_DYN', 0))
        roe = s.get('roe', s.get('ROE_WEIGHT', 0))
        pb = s.get('pb', s.get('PB_MRQ', 0))
        cap = s.get('market_cap', s.get('TOTAL_MARKET_CAP', 0))
        if cap and cap > 10000:
            cap = cap / 1e8
        
        print(f"\n{i:2d}. {name} ({code})")
        print(f"    💰 股价: ¥{price:.2f}  |  📊 PE: {pe:.2f}  |  📈 ROE: {roe:.2f}%")
        print(f"    📋 PB: {pb:.2f}  |  🏢 市值: {cap:.0f}亿")
        
        # 评级
        score = 0
        if pe < 8: score += 3
        elif pe < 12: score += 2
        else: score += 1
        if roe > 25: score += 3
        elif roe > 20: score += 2
        else: score += 1
        if pb and pb < 1.5: score += 1
        elif pb and pb < 2.5: score += 0.5
        
        stars = "⭐" * min(int(score), 5)
        print(f"    🎯 评级: {stars}")
    
    # 保存到文件
    import csv
    output_file = '/root/.openclaw/workspace/value_stocks_result.csv'
    with open(output_file, 'w', newline='', encoding='utf-8-sig') as f:
        if stocks and isinstance(stocks[0], dict):
            writer = csv.DictWriter(f, fieldnames=stocks[0].keys())
            writer.writeheader()
            writer.writerows(stocks[:50])
    print(f"\n💾 结果已保存: {output_file}")
    
else:
    print("\n❌ 未获取到数据，请检查网络连接")

print("\n" + "=" * 60)
print("📝 风险提示: 以上分析仅供参考，不构成投资建议。")
print("   投资有风险，入市需谨慎。- 蛋蛋基金 🥚")
print("=" * 60)
