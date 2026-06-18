#!/usr/bin/env python3
"""
价值投资扫描器 - 巴菲特选股标准
=============================
筛选条件：PE<15 且 ROE>15%
目标：中线1-3个月机会
"""

import sys
import time
import pandas as pd
from datetime import datetime

# 添加sim_trading路径
sys.path.insert(0, '/root/.openclaw/workspace/sim_trading')
import buffett_analyzer as ba

def get_all_a_stocks():
    """获取A股股票列表（使用akshare）"""
    try:
        import akshare as ak
        # 获取A股实时行情（包含代码、名称、价格等）
        df = ak.stock_zh_a_spot_em()
        if df is not None and not df.empty:
            return df
        else:
            print("❌ 无法获取A股数据")
            return None
    except Exception as e:
        print(f"❌ 获取A股数据失败: {e}")
        return None

def scan_value_stocks():
    """扫描价值股"""
    print("="*70)
    print("🥚 蛋蛋基金 - 巴菲特价值投资扫描")
    print(f"📅 扫描时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*70)
    print()
    print("📋 筛选条件：")
    print("   • PE(TTM) < 15倍（安全边际）")
    print("   • ROE > 15%（盈利能力）")
    print("   • 中线1-3个月机会")
    print()
    
    # 获取A股数据
    print("正在获取A股行情数据...")
    df_stocks = get_all_a_stocks()
    if df_stocks is None:
        return
    
    print(f"共获取 {len(df_stocks)} 只股票")
    print()
    
    # 筛选条件：先筛选一些典型的价值股行业（银行、白酒、家电、电力等）
    # 由于网络限制，我们先分析一些典型的价值股
    value_candidates = [
        # 银行股（PE通常较低）
        '600036',  # 招商银行
        '000001',  # 平安银行
        '601398',  # 工商银行
        '601939',  # 建设银行
        '601288',  # 农业银行
        '601166',  # 兴业银行
        '600000',  # 浦发银行
        '600016',  # 民生银行
        '601328',  # 交通银行
        '601169',  # 北京银行
        
        # 白酒股（ROE通常较高）
        '600519',  # 贵州茅台
        '000858',  # 五粮液
        '000568',  # 泸州老窖
        '002304',  # 洋河股份
        '600809',  # 山西汾酒
        '000596',  # 古井贡酒
        
        # 家电股
        '000333',  # 美的集团
        '000651',  # 格力电器
        '600690',  # 海尔智家
        
        # 电力股
        '600900',  # 长江电力
        '600011',  # 华能国际
        '600027',  # 华电国际
        
        # 保险股
        '601318',  # 中国平安
        '601628',  # 中国人寿
        '601601',  # 中国太保
        
        # 医药股
        '600276',  # 恒瑞医药
        '000538',  # 云南白药
        '600196',  # 复星医药
        
        # 基建股
        '601668',  # 中国建筑
        '601390',  # 中国中铁
        '601186',  # 中国铁建
    ]
    
    print("正在筛选价值股（PE<15 且 ROE>15%）...")
    print()
    
    value_stocks = []
    analyzed_count = 0
    
    for code in value_candidates:
        try:
            analyzed_count += 1
            if analyzed_count % 10 == 0:
                print(f"  已分析 {analyzed_count}/{len(value_candidates)} 只股票...")
            
            # 获取PE数据（使用akshare，更准确）
            import akshare as ak
            df_val = ak.stock_value_em(symbol=code)
            if df_val is None or df_val.empty:
                continue
                
            latest = df_val.iloc[-1]
            pe_ttm = latest.get('PE(TTM)')
            pb = latest.get('市净率')
            
            if not pe_ttm or pe_ttm <= 0 or pe_ttm >= 15:
                continue
            
            # 获取财务数据（ROE）
            financial = ba.get_financial_data(code)
            roe = financial.get('roe_latest')
            
            if not roe or roe < 15:
                continue
            
            # 获取股票名称和价格
            quote = ba.get_stock_info_from_tencent(code)
            if not quote:
                continue
                
            name = quote.get('name', code)
            price = quote.get('price', 0)
            
            # 计算得分
            result = ba.calc_buffett_score(quote, financial, None)
            
            value_stocks.append({
                'code': code,
                'name': name,
                'price': price,
                'pe': pe_ttm,
                'roe': roe,
                'pb': pb,
                'score': result['total_score'],
                'stars': result['stars'],
                'action': result['action'],
                'target_price': result.get('target_price'),
                'stop_price': result.get('stop_price'),
            })
            
            print(f"  ✅ {name}({code}) - PE={pe_ttm:.1f}, ROE={roe:.1f}%, 评分={result['total_score']}")
            
            # 避免请求过快
            time.sleep(0.5)
            
        except Exception as e:
            print(f"  ❌ 分析 {code} 失败: {e}")
            continue
    
    print()
    print("="*70)
    print(f"📊 扫描结果：共找到 {len(value_stocks)} 只价值股")
    print("="*70)
    
    if not value_stocks:
        print("❌ 未找到符合 PE<15 且 ROE>15% 的价值股")
        print()
        print("💡 可能原因：")
        print("   • 当前市场估值较高")
        print("   • 网络数据获取受限")
        print("   • 筛选条件较严格")
        return
    
    # 按评分排序
    value_stocks.sort(key=lambda x: x['score'], reverse=True)
    
    print()
    print("🏆 TOP 价值股排名：")
    print("-"*70)
    
    for i, stock in enumerate(value_stocks, 1):
        print(f"\n{i}. {stock['name']}（{stock['code']}）")
        print(f"   💰 现价: ¥{stock['price']:.2f}")
        print(f"   📊 PE(TTM): {stock['pe']:.1f} | ROE: {stock['roe']:.1f}% | PB: {stock['pb']:.2f}")
        print(f"   ⭐ 评分: {stock['score']}/100 {'⭐' * stock['stars']}")
        print(f"   📋 建议: {stock['action']}")
        
        if stock['target_price'] and stock['stop_price']:
            upside = (stock['target_price'] - stock['price']) / stock['price'] * 100
            print(f"   🎯 目标价: ¥{stock['target_price']:.2f} (+{upside:.1f}%)")
            print(f"   🛡️  止损价: ¥{stock['stop_price']:.2f}")
    
    print()
    print("-"*70)
    print("📌 中线操作建议（1-3个月）：")
    print("   • 分批建仓，避免一次性买入")
    print("   • 设置止损位，控制风险")
    print("   • 关注季度财报，验证ROE稳定性")
    print("   • 耐心持有，价值回归需要时间")
    print()
    print("⚠️  风险提示：")
    print("   • 本分析仅供参考，不构成投资建议")
    print("   • 股市有风险，投资需谨慎")
    print("   • 价值投资需要长期视角")
    print()
    
    # 保存结果到文件
    df_result = pd.DataFrame(value_stocks)
    output_file = f"/root/.openclaw/workspace/value_stocks_scan_{datetime.now().strftime('%Y%m%d')}.csv"
    df_result.to_csv(output_file, index=False, encoding='utf-8-sig')
    print(f"💾 详细数据已保存到: {output_file}")

if __name__ == "__main__":
    scan_value_stocks()
