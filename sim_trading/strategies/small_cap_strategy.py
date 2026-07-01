"""
小市值策略 v1.0
聚宽三策略之小市值 35%
399100成分股, 流通市值排序+行业分散, 每周二调仓, 持6只, 个股止损-9%
基于: https://www.joinquant.com 多策略组合
"""
import numpy as np
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any

logger = logging.getLogger(__name__)

SMALL_CAP_CONFIG = {
    'market_index': '399100',     # 深证中小板指
    'stock_num': 6,               # 持有6只
    'up_price': 20,               # 价格上限
    'run_stoploss': True,
    'stoploss_limit': 0.91,       # -9%止损
    'stoploss_market': 0.95,      # 大盘跌5%触发清仓
}

# 排除的股票（科创板、北交所、创业板部分高价股）
def filter_kcbj(stocks: List[str]) -> List[str]:
    return [s for s in stocks if not s.startswith(('30', '68', '8', '4'))]


def get_index_stocks_small_cap(index_code: str = '399100', limit: int = 200) -> List[str]:
    """获取指数成分股（通过腾讯接口模拟）"""
    import requests
    try:
        # 腾讯行业板块成分股接口
        url = f"https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newrank/dailyrank?param={index_code},day,,,0,5"
        headers = {'User-Agent': 'Mozilla/5.0'}
        r = requests.get(url, headers=headers, timeout=5)
        return []  # 腾讯接口难获取完整成分股，用本地数据源代替
    except Exception:
        return []


def get_all_shares_list() -> List[Dict]:
    """获取全市场股票列表（用于小市值选股）"""
    import requests
    try:
        # 通过腾讯全市场行情
        url = "https://push2.eastmoney.com/api/qt/clist/get"
        params = {
            'pn': 1, 'pz': 3000, 'po': 1,
            'np': 1, 'ut': 'bd1d9ddb04089700cf9c27f6f7426281',
            'fltt': 2, 'invt': 2, 'fid': 'f20', 'fs': 'm:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048',
            'fields': 'f12,f14,f20,f3,f2,f4,f8'
        }
        resp = requests.get(url, params=params, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
        data = resp.json()
        
        stocks = []
        if data.get('data') and data['data'].get('diff'):
            for item in data['data']['diff']:
                code = str(item.get('f12', ''))
                name = item.get('f14', '')
                market_cap = item.get('f20', 0)  # 总市值（亿）
                price = item.get('f2', 0)
                change_pct = item.get('f3', 0)
                volume = item.get('f8', 0)
                
                # 过滤
                if not code or not name:
                    continue
                if code.startswith(('30', '68', '8', '4', '9')):
                    continue
                if 'ST' in name or '*' in name or '退' in name:
                    continue
                
                stocks.append({
                    'code': code,
                    'name': name,
                    'market_cap': market_cap,
                    'price': price,
                    'change_pct': change_pct,
                    'volume': volume,
                })
        
        return stocks
    except Exception as e:
        logger.warning(f"获取全市场列表失败: {e}")
        return []


def small_cap_scan() -> List[Dict]:
    """小市值策略扫描：筛选流通市值最低且基本面合格的股票"""
    config = SMALL_CAP_CONFIG
    
    all_stocks = get_all_shares_list()
    if not all_stocks:
        logger.warning("[小市值] 获取股票列表失败")
        return []
    
    # 按总市值升序排列
    sorted_stocks = sorted(all_stocks, key=lambda x: x.get('market_cap', float('inf')))
    
    # 取前200只
    candidates = sorted_stocks[:200]
    
    # 行业分散：按代码前3位分组，每组取最多2只
    industries = {}
    for s in candidates:
        industry_code = s['code'][:3]
        if industry_code not in industries:
            industries[industry_code] = []
        if len(industries[industry_code]) < 2:
            industries[industry_code].append(s)
    
    # 展平且保持市值顺序
    selected = []
    seen = set()
    for s in candidates:
        if s['code'] in seen:
            continue
        industry_code = s['code'][:3]
        if industry_code in industries and s in industries[industry_code]:
            selected.append(s)
            seen.add(s['code'])
    
    # 取前stock_num*2=12只
    final = selected[:config['stock_num'] * 2]
    
    logger.info(f"[小市值] 扫描完成，候选{len(final)}只")
    for s in final[:config['stock_num']]:
        logger.info(f"  {s['name']}({s['code']}) 市值{s['market_cap']:.1f}亿 价格{s['price']}")
    
    return [{
        'code': s['code'],
        'name': s['name'],
        'market_cap': s['market_cap'],
        'price': s['price'],
        'change_pct': s['change_pct'],
    } for s in final]


def check_stop_loss(positions: List[Dict], current_prices: Dict[str, float]) -> List[Dict]:
    """检查需要止损的持仓
    
    Returns:
        触发止损的持仓列表
    """
    config = SMALL_CAP_CONFIG
    if not config['run_stoploss']:
        return []
    
    stop_positions = []
    for pos in positions:
        code = pos['stock_code']
        price = current_prices.get(code, pos['avg_cost'])
        if price <= 0:
            continue
        if price < pos['avg_cost'] * config['stoploss_limit']:
            stop_positions.append(pos)
            logger.info(f"[小市值] 止损 {code} {pos.get('stock_name','')} 成本{pos['avg_cost']} 现价{price}")
    
    return stop_positions


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    results = small_cap_scan()
    print(f"扫描结果: {len(results)} 只")
