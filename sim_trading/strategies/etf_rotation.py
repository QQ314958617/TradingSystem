"""
ETF轮动策略 v1.0
聚宽三策略之ETF轮动40%
动量评分+ETF溢价过滤，每日换仓持有最强ETF
基于: https://www.joinquant.com 多策略组合
"""
import numpy as np
import math
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# ETF池
ETF_POOL = [
    "513100",  # 纳指ETF
    "159525",  # 中证2000
    "513130",  # 恒生科技
    "159915",  # 创业板
    "159628",  # 中证1000
    "588120",  # 科创50
    "513520",  # 日经ETF
    "513030",  # 德国ETF
    "518880",  # 黄金ETF
    "161226",  # 白银基金
    "159985",  # 豆粕ETF
    "501018",  # 南方原油
    "159652",  # 标普500
    "511090",  # 国债ETF
]

# ETF 代码映射到聚宽代码（用于查询）
ETF_JJCODES = {
    "513100": "513100.XSHG",
    "159525": "159525.XSHE",
    "513130": "513130.XSHG",
    "159915": "159915.XSHE",
    "159628": "159628.XSHE",
    "588120": "588120.XSHG",
    "513520": "513520.XSHG",
    "513030": "513030.XSHG",
    "518880": "518880.XSHG",
    "161226": "161226.XSHE",
    "159985": "159985.XSHE",
    "501018": "501018.XSHG",
    "159652": "159652.XSHE",
    "511090": "511090.XSHG",
}

# ETF腾讯代码前缀映射
ETF_TENCENT_PREFIX = {
    "513100": "sh", "159525": "sz", "513130": "sh", "159915": "sz",
    "159628": "sz", "588120": "sh", "513520": "sh", "513030": "sh",
    "518880": "sh", "161226": "sz", "159985": "sz", "501018": "sh",
    "159652": "sz", "511090": "sh",
}

# ETF名称映射
ETF_NAMES = {
    "513100": "纳指ETF",
    "159525": "中证2000",
    "513130": "恒生科技",
    "159915": "创业板",
    "159628": "中证1000",
    "588120": "科创50",
    "513520": "日经ETF",
    "513030": "德国ETF",
    "518880": "黄金ETF",
    "161226": "白银基金",
    "159985": "豆粕ETF",
    "501018": "南方原油",
    "159652": "标普500",
    "511090": "国债ETF",
}

ETF_STRATEGY_CONFIG = {
    'etf_pool': ETF_POOL,
    'target_num': 1,            # 只持有最强1只
    'min_days': 20,             # 最小回看周期
    'max_days': 60,             # 最大回看周期
    'premium_threshold': 5.0,   # 溢价5%以上扣分
}


def get_etf_kline(etf_code: str, days: int) -> Optional[Dict]:
    """获取ETF日K线数据（通过交易系统行情API或腾讯接口）"""
    import requests
    try:
        prefix = ETF_TENCENT_PREFIX.get(etf_code, "sh")
        tencent_code = prefix + etf_code
        
        # 腾讯行情接口
        url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={tencent_code},day,,,{days},qfq"
        headers = {'User-Agent': 'Mozilla/5.0'}
        r = requests.get(url, headers=headers, timeout=5)
        data = r.json()
        
        # 解析腾讯返回格式
        if data.get('code') == 0:
            kdata = data.get('data', {})
            if tencent_code in kdata:
                days_data = kdata[tencent_code].get('day', kdata[tencent_code].get('qfqday', []))
                if days_data and len(days_data) >= min(days, 10):
                    closes = [float(d[2]) for d in days_data[-days:]]
                    highs = [float(d[3]) for d in days_data[-days:]]
                    lows = [float(d[4]) for d in days_data[-days:]]
                    return {'close': closes, 'high': highs, 'low': lows, 'dates': [d[0] for d in days_data[-days:]]}
        
        # 备用：通过本地行情API
        resp = requests.get(f"http://localhost/api/quote/{etf_code}", timeout=5)
        q = resp.json()
        if q.get('price'):
            return {'close': [q['price']], 'high': [q.get('high', q['price'])], 'low': [q.get('low', q['price'])], 'dates': [datetime.now().strftime('%Y-%m-%d')]}
    except Exception as e:
        logger.warning(f"获取{etf_code} K线失败: {e}")
    return None


def get_etf_quote(etf_code: str) -> Optional[Dict]:
    """获取ETF实时行情"""
    try:
        import requests
        resp = requests.get(f"http://localhost/api/quote/{etf_code}", timeout=5)
        return resp.json()
    except Exception as e:
        logger.warning(f"获取{etf_code}行情失败: {e}")
    return None


def calc_momentum_score(kline: Dict, use_auto: bool = True, 
                         min_days: int = 20, max_days: int = 60) -> Tuple[float, float]:
    """计算ETF动量评分
    
    Returns:
        (score, annualized_return) 评分和年化收益
    """
    closes = kline['close']
    highs = kline['high']
    lows = kline['low']
    
    if len(closes) < min_days:
        return 0, 0
    
    # 动态周期
    if use_auto:
        # 用ATR波动率计算自适应周期
        try:
            close_arr = np.array(closes, dtype=float)
            high_arr = np.array(highs, dtype=float)
            low_arr = np.array(lows, dtype=float)
            
            def calc_atr(h, l, c, period):
                if len(h) < period + 1:
                    return np.array([np.mean(h - l)] * period)
                tr = np.maximum(h[1:] - l[1:], 
                                np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
                atr = np.zeros(period)
                atr[0] = np.mean(tr[:period])
                for i in range(1, period):
                    atr[i] = (atr[i-1] * (period-1) + tr[i]) / period
                return atr
            
            long_atr = calc_atr(high_arr, low_arr, close_arr, max_days)
            short_atr = calc_atr(high_arr, low_arr, close_arr, min_days)
            
            if len(long_atr) > 0 and len(short_atr) > 0 and long_atr[-1] > 0:
                vol_ratio = min(0.9, short_atr[-1] / long_atr[-1])
                lookback = int(min_days + (max_days - min_days) * (1 - vol_ratio))
            else:
                lookback = (min_days + max_days) // 2
        except Exception:
            lookback = (min_days + max_days) // 2
    else:
        lookback = min_days
    
    # 取最近lookback天的价格
    prices = np.array(closes[-lookback:], dtype=float)
    
    if len(prices) < 5:
        return 0, 0
    
    # 对数收益率 + 加权线性拟合
    y = np.log(prices)
    x = np.arange(len(y))
    weights = np.linspace(1, 2, len(y))
    
    try:
        # 加权最小二乘
        W = np.diag(weights)
        X = np.vstack([np.ones(len(x)), x]).T
        beta = np.linalg.inv(X.T @ W @ X) @ (X.T @ W @ y)
        slope = beta[1]
        
        annualized_return = math.exp(slope * 250) - 1
        
        # R²
        y_pred = X @ beta
        ss_res = np.sum(weights * (y - y_pred) ** 2)
        ss_tot = np.sum(weights * (y - np.mean(y)) ** 2)
        r2 = 1 - ss_res / ss_tot if ss_tot != 0 else 0
        
        score = annualized_return * r2
        
        # 近期跌幅惩罚
        if len(prices) >= 4:
            recent_min = min(prices[-1]/prices[-2], prices[-2]/prices[-3], prices[-3]/prices[-4])
            if recent_min < 0.95:
                score = 0
            # 连续下跌惩罚
            if prices[-1] < prices[-2] and prices[-2] < prices[-3] and prices[-3] < prices[-4] and prices[-1]/prices[-4] < 0.95:
                score = 0
        
        return score, annualized_return
    
    except Exception as e:
        logger.warning(f"动量计算失败: {e}")
        return 0, 0


def etf_rotation_scan() -> List[Dict]:
    """ETF轮动扫描：返回排序后的ETF评分列表"""
    config = ETF_STRATEGY_CONFIG
    results = []
    
    for code in config['etf_pool']:
        try:
            kline = get_etf_kline(code, config['max_days'] + 10)
            if not kline or len(kline.get('close', [])) < config['min_days']:
                continue
            
            score, ann_ret = calc_momentum_score(
                kline, use_auto=True,
                min_days=config['min_days'],
                max_days=config['max_days']
            )
            
            if score <= 0 or score >= 6:
                continue
            
            # 获取当前价格
            quote = get_etf_quote(code)
            price = quote.get('price', kline['close'][-1]) if quote else kline['close'][-1]
            change_pct = quote.get('change_pct', 0) if quote else 0
            
            results.append({
                'code': code,
                'name': ETF_NAMES.get(code, code),
                'score': round(score, 4),
                'annualized_return': round(ann_ret * 100, 2),
                'price': price,
                'change_pct': change_pct,
            })
        except Exception as e:
            logger.warning(f"扫描{code}异常: {e}")
            continue
    
    # 按评分排序
    results.sort(key=lambda x: x['score'], reverse=True)
    
    logger.info(f"[ETF轮动] 扫描完成，有效ETF: {len(results)}只")
    for r in results[:5]:
        logger.info(f"  {r['name']}({r['code']}) 评分:{r['score']} 年化:{r['annualized_return']}%")
    
    return results


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    results = etf_rotation_scan()
    if results:
        print(f"\n最佳ETF: {results[0]['name']}({results[0]['code']}) 评分:{results[0]['score']}")
