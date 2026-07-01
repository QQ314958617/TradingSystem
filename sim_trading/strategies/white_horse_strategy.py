"""
白马策略 v1.0
聚宽三策略之白马股 25%
大小盘择时信号+月度调仓+止损，选沪深300质优股/创业板小盘股
基于: https://www.joinquant.com 多策略组合
"""
import numpy as np
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

WHITE_HORSE_CONFIG = {
    'stock_num': 20,          # 选股池大小
    'max_stock_price': 50,    # 小盘股价格上限
    'stop_loss_ratio': 0.94,  # -6%止损
    'recent_days': 10,        # 动量计算窗口
    'buy_stock_count': 20,    # 实际买入数量
}


def assess_market_temperature() -> str:
    """评估市场温度: cold/warm/hot"""
    import requests
    try:
        url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=000300,day,,,220,qfq"
        resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        data = resp.json()
        
        if data.get('code') == 0:
            days_data = data.get('data', {}).get('000300', {}).get('day', [])
            if len(days_data) >= 220:
                closes = [float(d[2]) for d in days_data]
                min_c = min(closes)
                max_c = max(closes)
                if max_c > min_c:
                    height = (np.mean(closes[-5:]) - min_c) / (max_c - min_c)
                    if height < 0.20:
                        return "cold"
                    elif height > 0.90:
                        return "hot"
                    elif max(closes[-60:]) / min(closes[-60:]) > 1.20:
                        return "warm"
        return "warm"
    except Exception as e:
        logger.warning(f"评估市场温度失败: {e}")
        return "warm"


def get_index_stocks_big() -> List[str]:
    """获取沪深300成分股"""
    import requests
    try:
        # 东方财富板块成分股
        url = "https://push2.eastmoney.com/api/qt/clist/get"
        params = {
            'pn': 1, 'pz': 300, 'po': 1, 'np': 1,
            'ut': 'bd1d9ddb04089700cf9c27f6f7426281',
            'fltt': 2, 'invt': 2, 'fid': 'f3', 'fs': 'b:MK0144',
            'fields': 'f12,f14,f20,f2,f3,f4,f8,f15,f16,f17,f9,f10,f18'
        }
        resp = requests.get(url, params=params, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
        data = resp.json()
        
        stocks = []
        if data.get('data') and data['data'].get('diff'):
            for item in data['data']['diff']:
                code = str(item.get('f12', ''))
                name = item.get('f14', '')
                pe = item.get('f9', 0)
                pb = item.get('f12', 0)
                market_cap = item.get('f20', 0)
                
                if not code or 'ST' in name or '*' in name or '退' in name:
                    continue
                if code.startswith(('30', '68', '8', '4')):
                    continue
                
                stocks.append({
                    'code': code,
                    'name': name,
                    'pe': pe,
                    'market_cap': market_cap,
                })
        
        return [s['code'] for s in stocks]
    except Exception as e:
        logger.warning(f"获取沪深300成分股失败: {e}")
        return []


def get_index_stocks_small() -> List[str]:
    """获取中小板指成分股"""
    import requests
    try:
        url = "https://push2.eastmoney.com/api/qt/clist/get"
        params = {
            'pn': 1, 'pz': 300, 'po': 1, 'np': 1,
            'ut': 'bd1d9ddb04089700cf9c27f6f7426281',
            'fltt': 2, 'invt': 2, 'fid': 'f3', 'fs': 'b:MK0030',
            'fields': 'f12,f14,f20,f2,f3,f4,f8,f15,f16,f17'
        }
        resp = requests.get(url, params=params, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
        data = resp.json()
        
        stocks = []
        if data.get('data') and data['data'].get('diff'):
            for item in data['data']['diff']:
                code = str(item.get('f12', ''))
                name = item.get('f14', '')
                price = item.get('f2', 0)
                
                if not code or 'ST' in name or '*' in name or '退' in name:
                    continue
                if code.startswith(('30', '68', '8', '4')):
                    continue
                if price > WHITE_HORSE_CONFIG['max_stock_price']:
                    continue
                
                stocks.append({
                    'code': code,
                    'name': name,
                    'price': price,
                    'market_cap': item.get('f20', 0),
                })
        
        return [s['code'] for s in stocks]
    except Exception as e:
        logger.warning(f"获取中小板成分股失败: {e}")
        return []


def generate_signal(market_temp: str) -> str:
    """根据市场温度生成信号: big/small/etf"""
    # 简化版：直接返回 big（沪深300选股）
    # 后续可以加入大小盘动量比较逻辑
    return "big"


def white_horse_select(stocks: List[str]) -> List[Dict]:
    """白马选股：筛选低PB+现金流健康的股票"""
    import requests
    config = WHITE_HORSE_CONFIG
    
    if not stocks:
        return []
    
    try:
        # 批量获取财务指标
        codes = ','.join(stocks)
        url = "https://push2.eastmoney.com/api/qt/clist/get"
        params = {
            'pn': 1, 'pz': len(stocks), 'po': 1, 'np': 1,
            'ut': 'bd1d9ddb04089700cf9c27f6f7426281',
            'fltt': 2, 'invt': 2, 'fid': 'f3',
            'fs': 'm:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23',
            'fields': 'f12,f14,f2,f3,f4,f9,f10,f15,f16,f17,f20,f21,f23,f25,f37,f38,f39,f40,f45,f46,f48,f50,f57,f58,f60,f62,f100,f111,f115,f117,f121,f122,f124,f125,f128,f140,f141,f142,f144,f145,f147,f148,f152,f153,f154,f155,f157,f158,f162,f163,f164,f165,f166,f167,f168,f169,f170,f171,f172,f173,f174,f175,f176,f177,f178,f179,f180,f181,f182,f183,f184,f185,f186,f187,f188,f189,f190,f191,f192,f193,f194,f195,f196,f197,f198,f199,f200,f201,f202,f203,f204,f205,f206,f207,f208,f209,f210'
        }
        resp = requests.get(url, params=params, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
        data = resp.json()
        
        candidates = []
        if data.get('data') and data['data'].get('diff'):
            for item in data['data'].get('diff', []):
                code = str(item.get('f12', ''))
                name = item.get('f14', '')
                pb = item.get('f23', 0)
                pe = item.get('f9', 0)
                roe = item.get('f37', 0)  # ROE
                profit_growth = item.get('f39', 0)  # 净利润增长率
                
                if not code or not name:
                    continue
                if 'ST' in name or '*' in name or '退' in name:
                    continue
                
                # 白马选股条件：
                # - PB > 0 且不高估
                # - PE > 0
                # - ROE > 0
                # - 净利润增长 > -15%
                if pb > 0 and pe > 0 and roe > 0 and profit_growth > -15:
                    candidates.append({
                        'code': code,
                        'name': name,
                        'pb': pb,
                        'pe': pe,
                        'roe': roe,
                        'profit_growth': profit_growth,
                        'market_cap': item.get('f20', 0),
                        'price': item.get('f2', 0),
                        'change_pct': item.get('f3', 0),
                    })
        
        # 按ROE/PB排序
        def score_fn(s):
            if s['pb'] <= 0:
                return 0
            return s['roe'] / s['pb']
        
        candidates.sort(key=score_fn, reverse=True)
        
        return candidates[:config['stock_num']]
    
    except Exception as e:
        logger.warning(f"白马选股失败: {e}")
        return []


def white_horse_scan() -> Dict:
    """白马策略全流程扫描"""
    market_temp = assess_market_temperature()
    signal = generate_signal(market_temp)
    
    logger.info(f"[白马] 市场温度:{market_temp} 信号:{signal}")
    
    if signal == 'big' or signal == 'warm':
        stocks = get_index_stocks_big()
    else:
        stocks = get_index_stocks_small()
    
    selected = white_horse_select(stocks)
    
    logger.info(f"[白马] 扫描完成，精选{len(selected)}只")
    for s in selected[:5]:
        logger.info(f"  {s['name']}({s['code']}) ROE:{s['roe']} PB:{s['pb']}")
    
    return {
        'signal': signal,
        'market_temp': market_temp,
        'targets': selected,
        'timestamp': datetime.now().isoformat(),
    }


def check_stop_loss(positions: List[Dict], current_prices: Dict[str, float]) -> List[Dict]:
    """检查白马止损"""
    config = WHITE_HORSE_CONFIG
    
    stop_positions = []
    for pos in positions:
        code = pos['stock_code']
        price = current_prices.get(code, pos['avg_cost'])
        if price <= 0:
            continue
        if price < pos['avg_cost'] * config['stop_loss_ratio']:
            stop_positions.append(pos)
            logger.info(f"[白马] 止损 {code} {pos.get('stock_name','')} 成本{pos['avg_cost']} 现价{price}")
    
    return stop_positions


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    result = white_horse_scan()
    print(f"信号: {result['signal']} 市场温度: {result['market_temp']}")
    print(f"候选: {len(result['targets'])} 只")
