#!/usr/bin/env python3
"""
价值投资全市场扫描器 v1.0
策略2专用：筛选PE<30、ROE>12%、营收增长>0%、负债率<65%的价值标的
输出JSON供蛋蛋交易系统分析
"""
import sys, os, json, time, requests
import pandas as pd
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 接入value_analyzer
from value_analyzer import (
    get_realtime_quote, get_stock_valuation,
    get_financial_indicators, calculate_value_score
)
from market_scanner import get_all_code_list, batch_tencent_quotes

# ===== 价值投资选股标准 =====
VALUE_CRITERIA = {
    'pe_max': 30,        # PE<30
    'roe_min': 12,       # ROE>12%
    'revenue_growth_min': 0,  # 营收增长>0%
    'debt_ratio_max': 65,     # 负债率<65%
    'mv_min': 30,        # 最小流通市值(亿) - 排除垃圾股
    'mv_max': 5000,      # 最大流通市值(亿)
}

# 已知价值股候选池（传统价值蓝筹+白马股，全市场预筛太慢）
VALUE_POOL = [
    # 银行
    '600036','601166','600000','601398','601939','601288','601988',
    '600016','601009','600015','601818','601328','601229',
    # 保险
    '601318','601628','601601','601336',
    # 地产
    '000002','600048','600383','001979',
    # 基建/交运
    '601800','601390','601668','601186','601618',
    '000088','600017','601006','601333',
    # 家电
    '000333','000651','600690','000100',
    # 汽车
    '600104','000625','601238','600741',
    # 建材
    '600585','000786','002271','600801',
    # 煤炭
    '601088','600188','600546','000983',
    # 电力/公用
    '600900','600886','000543','601985','600011','600023',
    # 钢铁
    '600019','000708','600010','000898',
    # 化工
    '600309','000830','002601','600352',
    # 食品/消费
    '600519','000858','002304','600887','000895',
    # 医药
    '600276','000538','300760','002007',
    # 机械
    '600031','000157','600150',
    # 通信科技
    '600941','000063','601728',
    # 港口/高速
    '600017','600012','600377','600548',
    # 商业
    '600827','601933',
    '000088',  # 盐田港
]


def quick_tencent_pe(debt, code):
    """从腾讯行情提取估值指标"""
    q = f"sh{code}" if code.startswith(('6','5')) else f"sz{code}"
    try:
        r = requests.get(f"https://qt.gtimg.cn/q={q}", timeout=8, headers={
            'User-Agent': 'Mozilla/5.0',
            'Referer': 'https://gu.qq.com/'
        })
        fields = r.text.split('="')[1].strip('"').split('~')
        if len(fields) < 46:
            return None
        return {
            'price': float(fields[3]) if fields[3] not in ('','-') else 0,
            'change_pct': float(fields[32]) if len(fields) > 32 and fields[32] not in ('','-') else 0,
            'pe': float(fields[41]) if len(fields) > 41 and fields[41] not in ('','-','0') else None,
            'pb': float(fields[43]) if len(fields) > 43 and fields[43] not in ('','-','0') else None,
            'mv_yi': float(fields[44]) if len(fields) > 44 and fields[44] not in ('','-') else None,
        }
    except:
        return None


def screener_v2():
    """
    策略2价值扫描器v2 — 基于候选池，避免全市场7600只股的慢扫描
    """
    results = []
    errors = []
    
    total = len(VALUE_POOL)
    print(f"🔍 开始价值投资扫描：{total}只候选股...", file=sys.stderr)
    
    for idx, code in enumerate(VALUE_POOL):
        if (idx + 1) % 10 == 0:
            print(f"  进度 {idx+1}/{total}", file=sys.stderr)
        
        try:
            # 1. 腾讯行情获取PE(快)
            qt = quick_tencent_pe(None, code)
            if qt is None or qt['price'] == 0:
                continue
            
            # 2. PE预过滤
            if qt['pe'] and qt['pe'] > VALUE_CRITERIA['pe_max']:
                continue
            if qt['mv_yi'] and (qt['mv_yi'] < VALUE_CRITERIA['mv_min'] or qt['mv_yi'] > VALUE_CRITERIA['mv_max']):
                continue
            
            # 3. 财务深度分析（慢，只在PE通过后执行）
            financial = get_financial_indicators(code)
            roe = financial.get('roe')
            debt = financial.get('debt_ratio')
            rev_growth = financial.get('revenue_growth')
            
            # 4. 标准过滤
            if roe is not None and roe < VALUE_CRITERIA['roe_min']:
                continue
            if debt is not None and debt > VALUE_CRITERIA['debt_ratio_max']:
                continue
            if rev_growth is not None and rev_growth < VALUE_CRITERIA['revenue_growth_min']:
                continue
            
            # 5. 获取估值详情
            valuation = get_stock_valuation(code)
            pe = valuation.get('pe') or qt.get('pe')
            pb = valuation.get('pb') or qt.get('pb')
            
            # 6. 评分
            quote_data = {'price': qt['price'], 'name': ''}
            score = calculate_value_score(
                quote_data,
                {'pe': pe, 'pb': pb, 'source': valuation.get('source', '')},
                financial
            )
            
            # 获取名字
            name = qt.get('name', '')
            try:
                q = f"sh{code}" if code.startswith(('6','5')) else f"sz{code}"
                r = requests.get(f"https://qt.gtimg.cn/q={q}", timeout=3)
                name = r.text.split('="')[1].split('~')[1]
            except:
                pass
            
            results.append({
                'code': code,
                'name': name,
                'price': qt['price'],
                'change_pct': qt['change_pct'],
                'pe': pe,
                'pb': pb,
                'roe': roe,
                'debt_ratio': debt,
                'revenue_growth': rev_growth,
                'profit_growth': financial.get('profit_growth'),
                'gross_margin': financial.get('gross_margin'),
                'mv_yi': qt['mv_yi'],
                'total_score': score['total_score'],
                'rating': score['rating'],
                'stars': score['stars'],
                'target_price': score['target_price'],
                'stop_price': score['stop_price'],
                'action': score['action'],
                'financial_source': financial.get('source', ''),
                'valuation_source': valuation.get('source', ''),
            })
        except Exception as e:
            errors.append({'code': code, 'error': str(e)})
    
    # 按评分排序
    results.sort(key=lambda x: x['total_score'], reverse=True)
    
    print(f"\n✅ 扫描完成！通过筛选: {len(results)} 只, 错误: {len(errors)}", file=sys.stderr)
    
    return {
        'scan_time': time.strftime('%Y-%m-%d %H:%M:%S'),
        'criteria': VALUE_CRITERIA,
        'candidates': results,
        'errors': errors[:10],
        'total_candidates': len(results),
    }


if __name__ == '__main__':
    import pprint
    result = screener_v2()
    print(json.dumps(result, ensure_ascii=False, indent=2))
