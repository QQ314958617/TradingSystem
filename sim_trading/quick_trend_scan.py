#!/usr/bin/env python3
"""快速趋势深度分析 - 基于fullscan数据对候选股做多因子评分"""
import sys, os, json, time, requests
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from strategies.trend_strategy import TrendFollowingStrategy

API_BASE = "http://localhost/api"

def main():
    print("=" * 60)
    print("🔍 趋势跟踪深度分析（基于fullscan候选数据）")
    print("=" * 60)
    
    # 获取fullscan候选
    resp = requests.get(f"{API_BASE}/market/fullscan", timeout=15)
    data = resp.json()
    candidates = data.get('candidates', [])
    print(f"\n📊 从fullscan获取 {len(candidates)} 只候选股\n")
    
    if not candidates:
        print("无候选股，扫描结束")
        return []
    
    # 初始化策略
    strategy = TrendFollowingStrategy(strategy_id=3)
    
    # 按涨幅+量比排序取前30只分析
    candidates.sort(key=lambda x: x.get('change_pct', 0) * 0.6 + x.get('volume_ratio', 0) * 0.4, reverse=True)
    analyze_list = candidates[:30]
    
    passed = []
    for idx, stock in enumerate(analyze_list):
        code = stock['code']
        name = stock['name']
        
        try:
            result = strategy.check_trend_signal(code)
            if result and result.get('buy_signal'):
                score = result.get('total_score', 0)
                metrics = result.get('metrics', {})
                breakdown = result.get('score_breakdown', {})
                passed.append({
                    'code': code,
                    'name': name,
                    'score': score,
                    'price': stock.get('price', 0),
                    'change_pct': stock.get('change_pct', 0),
                    'volume_ratio': stock.get('volume_ratio', 0),
                    'market_cap': stock.get('circulate_mv_yi', 0),
                    'metrics': metrics,
                    'breakdown': breakdown,
                    'result': result,
                })
                print(f"  ✅ {name}({code}) | 评分{score}分 | "
                      f"涨{stock['change_pct']:.1f}% 量比{stock['volume_ratio']:.1f}")
                
            # 打印详情
            mom = result.get('score_breakdown', {}).get('momentum', {})
            vol = result.get('score_breakdown', {}).get('volume', {})
            ma = result.get('score_breakdown', {}).get('ma_trend', {})
            macd = result.get('score_breakdown', {}).get('macd', {})
            rsi = result.get('score_breakdown', {}).get('rsi', {})
            print(f"     评分: 总分{result.get('total_score',0)} | "
                  f"动量{mom.get('score',0)}/30 | 量{vol.get('score',0)}/23 | "
                  f"均线{ma.get('score',0)}/20 | MACD{macd.get('score',0)}/15 | "
                  f"RSI{rsi.get('score',0)}/15")
            if not result.get('buy_signal'):
                print(f"     未通过: {result.get('reason', '')[:80]}")
            
        except Exception as e:
            print(f"  ❌ {name}({code}) 分析错误: {e}")
        
        time.sleep(0.5)
    
    # 按评分排序
    passed.sort(key=lambda x: x['score'], reverse=True)
    
    print("\n" + "=" * 60)
    print(f"🏁 深度分析完成")
    print(f"   分析: {len(analyze_list)}只")
    print(f"   通过趋势筛选: {len(passed)}只")
    print("=" * 60)
    
    if passed:
        print("\n🎯 TOP候选股:")
        for i, s in enumerate(passed[:5], 1):
            print(f"  {i}. {s['name']}({s['code']}) | {s['score']}分")
            print(f"     涨{s['change_pct']:.1f}% | 量比{s['volume_ratio']:.1f} | 市值{s['market_cap']:.0f}亿")
            print(f"     价格{s['price']} | ATR{s['metrics'].get('atr_pct', 0)}%")
            if s['metrics'].get('hot_boards'):
                print(f"     热点板块: {','.join(s['metrics']['hot_boards'])}")
    
    # 输出JSON结果
    result_json = json.dumps(passed, ensure_ascii=False, indent=2, default=str)
    with open('/tmp/trend_scan_result.json', 'w') as f:
        f.write(result_json)
    
    print(f"\n📝 结果已保存到 /tmp/trend_scan_result.json")
    return passed


if __name__ == '__main__':
    results = main()
    if results:
        print("\n[NOTIFY]")
        print(f"🔍 趋势扫描完成 | 通过{len(results)}只")
        for s in results[:5]:
            print(f"  {s['name']}({s['code']}) {s['score']}分 | 涨{s['change_pct']:.1f}% 量比{s['volume_ratio']:.1f}")
