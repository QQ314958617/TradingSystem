"""
一夜持股法策略 v2.3
============================
买入：14:50-14:55 尾盘，7个条件全满足 → 满仓单票
卖出：次日 09:30-10:30 冲高即走
止损：-2%（无条件）
止盈：+5%~8%，从最高点回落 -2% 即卖
"""
import logging
import numpy as np
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any

from services.quote import get_tencent_quote, get_tencent_kline, calculate_rsi
from services.cache import cache

logger = logging.getLogger(__name__)

BJ_TZ = timezone(timedelta(hours=8))


# ═══════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════

def bj_now() -> datetime:
    return datetime.now(BJ_TZ)


def is_scan_window() -> bool:
    """是否在尾盘扫描窗口 14:45-14:55"""
    t = bj_now().time()
    from datetime import time as T
    return T(14, 45) <= t <= T(14, 55)


def is_buy_window() -> bool:
    """是否在买入窗口 14:50-14:55"""
    t = bj_now().time()
    from datetime import time as T
    return T(14, 50) <= t <= T(14, 55)


def is_sell_window() -> bool:
    """是否在次日早盘卖出窗口 09:25-10:30"""
    t = bj_now().time()
    from datetime import time as T
    return T(9, 25) <= t <= T(10, 30)


def calc_shares(cash: float, price: float) -> int:
    """按100股整数倍计算满仓股数"""
    if price <= 0:
        return 0
    return int(cash / price / 100) * 100


# ═══════════════════════════════════════════════
# 大盘指数获取
# ═══════════════════════════════════════════════

def get_index_change_pct() -> float:
    """获取上证指数当前涨跌幅"""
    try:
        quotes = get_tencent_quote(['000001'])
        return quotes.get('000001', {}).get('change_pct', 0.0)
    except Exception as e:
        logger.warning(f"大盘指数获取失败: {e}")
        return 0.0


# ═══════════════════════════════════════════════
# 个股行情增强（换手率 + 流通市值）
# ═══════════════════════════════════════════════

def get_stock_detail(code: str) -> dict:
    """
    获取个股详细行情（含换手率/流通市值）
    换手率 field[38]，流通市值 field[44]（亿元）
    """
    import requests
    prefix = 'sh' if code.startswith(('6', '5')) else 'sz'
    try:
        url = f"https://qt.gtimg.cn/q={prefix}{code}"
        headers = {
            'User-Agent': 'Mozilla/5.0',
            'Referer': 'https://gu.qq.com/'
        }
        r = requests.get(url, headers=headers, timeout=5)
        r.encoding = 'gbk'
        for line in r.text.strip().split('\n'):
            if '="' not in line:
                continue
            fields = line.split('="')[1].strip('"').split('~')
            if len(fields) < 46:
                continue
            def safe_float(idx, default=0.0):
                try:
                    v = fields[idx] if len(fields) > idx else ''
                    return float(v) if v not in ('', '-') else default
                except Exception:
                    return default
            return {
                'code': code,
                'name': fields[1],
                'price': safe_float(3),
                'close_yesterday': safe_float(4),
                'open': safe_float(5),
                'volume': safe_float(6),          # 手
                'amount': safe_float(37),          # 万元
                'high': safe_float(33),
                'low': safe_float(34),
                'change': safe_float(31),
                'change_pct': safe_float(32),
                'turnover': safe_float(38),        # 换手率 %
                'circulate_mv': safe_float(44),    # 流通市值 亿
                'volume_ratio': safe_float(49) if len(fields) > 49 else 1.0,
                'avg_price': safe_float(51) if len(fields) > 51 else 0.0,  # 分时均价
            }
    except Exception as e:
        logger.warning(f"get_stock_detail({code}) 失败: {e}")
    return {}


def get_volume_ratio_5d(code: str, current_volume: float) -> float:
    """
    计算当日成交量 vs 5日均量之比
    current_volume: 今日截至目前成交量（手）
    """
    try:
        klines = get_tencent_kline(code, days=10)
        if len(klines) < 5:
            return 1.0
        # kline 格式: [日期, 开盘, 收盘, 最高, 最低, 成交量(手), ...]
        recent_5 = [float(k[5]) for k in klines[-5:] if len(k) > 5]
        if not recent_5:
            return 1.0
        avg_5d = np.mean(recent_5)
        if avg_5d == 0:
            return 1.0
        return current_volume / avg_5d
    except Exception as e:
        logger.warning(f"成交量比计算失败({code}): {e}")
        return 1.0


def get_rsi(code: str, period: int = 14) -> float:
    """获取RSI"""
    try:
        klines = get_tencent_kline(code, days=period + 5)
        if not klines:
            return 50.0
        closes = [float(k[2]) for k in klines if len(k) > 2]
        return calculate_rsi(closes, period)
    except Exception as e:
        logger.warning(f"RSI计算失败({code}): {e}")
        return 50.0


# ═══════════════════════════════════════════════
# 7条件过滤（核心）
# ═══════════════════════════════════════════════

def check_conditions(detail: dict, rsi: float, vol_ratio_5d: float, index_change_pct: float) -> dict:
    """
    验证一夜持股法7个买入条件
    返回 {'pass': bool, 'score': float, 'details': {条件: 结果}}
    """
    code = detail.get('code', '')
    change_pct   = detail.get('change_pct', 0)
    turnover     = detail.get('turnover', 0)
    circulate_mv = detail.get('circulate_mv', 0)
    price        = detail.get('price', 0)
    avg_price    = detail.get('avg_price', 0)

    results = {}

    # ① 涨幅 3%-5%
    c1 = 3.0 <= change_pct <= 5.0
    results['change_pct']    = {'pass': c1, 'value': round(change_pct, 2), 'require': '3%~5%'}

    # ② 成交量 > 1.5倍5日均量
    c2 = vol_ratio_5d >= 1.5
    results['vol_ratio_5d']  = {'pass': c2, 'value': round(vol_ratio_5d, 2), 'require': '>1.5x'}

    # ③ 换手率 3%-10%
    c3 = 3.0 <= turnover <= 10.0
    results['turnover']      = {'pass': c3, 'value': round(turnover, 2), 'require': '3%~10%'}

    # ④ 流通市值 50-200亿
    c4 = 50.0 <= circulate_mv <= 200.0
    results['circulate_mv']  = {'pass': c4, 'value': round(circulate_mv, 1), 'require': '50~200亿'}

    # ⑤ RSI 40-65
    c5 = 40.0 <= rsi <= 65.0
    results['rsi']           = {'pass': c5, 'value': round(rsi, 1), 'require': '40~65'}

    # ⑥ 当前价 > 分时均价
    if avg_price > 0:
        c6 = price > avg_price
    else:
        # 无分时均价时跳过（不强制否决）
        c6 = True
    results['above_avg_price'] = {'pass': c6, 'value': round(price, 2), 'require': f'>均价{avg_price}'}

    # ⑦ 强于大盘
    c7 = change_pct > index_change_pct
    results['vs_index']      = {'pass': c7, 'value': round(change_pct - index_change_pct, 2), 'require': '>大盘涨幅'}

    all_pass = c1 and c2 and c3 and c4 and c5 and c6 and c7

    # 综合评分（择优排序用）
    score = 0.0
    if all_pass:
        score += rsi * 0.4                           # RSI越高动量越强
        score += min(vol_ratio_5d, 5.0) * 10        # 成交量放大，越大越好
        score += (change_pct - index_change_pct) * 5 # 强于大盘幅度
        score += min(turnover, 10.0) * 2             # 换手率
        score += (200.0 - circulate_mv) * 0.01       # 流通市值偏小加分

    return {'pass': all_pass, 'score': round(score, 2), 'details': results}


# ═══════════════════════════════════════════════
# 全市场扫描 + 候选股筛选
# ═══════════════════════════════════════════════

def scan_candidates() -> List[Dict]:
    """
    全市场扫描，返回满足7条件的候选股列表（按score降序）
    """
    import requests

    # 1. 东财全市场行情（约5000只）
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    params = {
        'pn': 1, 'pz': 5000, 'po': 1,
        'np': 1, 'ut': 'bd1d9ddb04089700cf9c27f6f7426281',
        'fltt': 2, 'invt': 2, 'fid': 'f3',
        'fs': 'm:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23',
        'fields': 'f12,f14,f2,f3,f4,f8,f20,f9,f10'
    }
    try:
        resp = requests.get(url, params=params,
                            headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
        diff = resp.json().get('data', {}).get('diff', [])
    except Exception as e:
        logger.error(f"东财行情获取失败: {e}")
        return []

    # 2. 大盘涨幅
    index_pct = get_index_change_pct()
    logger.info(f"大盘涨幅: {index_pct:.2f}%  候选池大小: {len(diff)}")

    # 3. 粗筛（涨幅3-5%，先排除明显不符合的）
    pre_candidates = []
    for item in diff:
        try:
            code = str(item.get('f12', ''))
            name = str(item.get('f14', ''))
            change_pct = float(item.get('f3', 0) or 0)
            price = float(item.get('f2', 0) or 0) / 100  # 东财价格单位分
            turnover = float(item.get('f8', 0) or 0)
            circulate_mv = float(item.get('f20', 0) or 0) / 100_000_000  # 转亿

            # 排除: ST/*退/科创板688/北交所8/无效价格
            if not code or not name or price <= 0:
                continue
            if code.startswith(('688', '8', '4', '9')):
                continue
            if 'ST' in name or '*' in name or '退' in name:
                continue

            # 粗筛涨幅
            if not (3.0 <= change_pct <= 5.0):
                continue

            pre_candidates.append({
                'code': code, 'name': name,
                'price': price,
                'change_pct': change_pct,
                'turnover': turnover,
                'circulate_mv': circulate_mv,
            })
        except Exception:
            continue

    logger.info(f"粗筛后候选: {len(pre_candidates)} 只")
    if not pre_candidates:
        return []

    # 4. 精筛：逐只获取详细数据
    results = []
    for item in pre_candidates:
        code = item['code']
        try:
            # 获取详细行情（换手率/分时均价/精确流通市值）
            detail = get_stock_detail(code)
            if not detail or detail.get('price', 0) <= 0:
                continue

            # 覆盖粗筛数据
            item.update({
                'price':        detail['price'],
                'change_pct':   detail['change_pct'],
                'turnover':     detail['turnover'],
                'circulate_mv': detail['circulate_mv'],
                'avg_price':    detail.get('avg_price', 0),
                'name':         detail.get('name', item['name']),
            })

            # 成交量比（需K线，较慢）
            vol_ratio = get_volume_ratio_5d(code, detail.get('volume', 0))

            # RSI
            rsi = get_rsi(code)

            # 验证7条件
            check = check_conditions(item, rsi, vol_ratio, index_pct)
            if check['pass']:
                item['rsi'] = rsi
                item['vol_ratio_5d'] = round(vol_ratio, 2)
                item['score'] = check['score']
                item['condition_details'] = check['details']
                results.append(item)
                logger.info(f"✅ {code} {item['name']} 通过 score={check['score']}")
            else:
                failed = [k for k, v in check['details'].items() if not v['pass']]
                logger.debug(f"❌ {code} {item['name']} 未通过: {failed}")

        except Exception as e:
            logger.warning(f"精筛 {code} 异常: {e}")
            continue

    # 5. 按评分降序排列
    results.sort(key=lambda x: x['score'], reverse=True)
    logger.info(f"最终候选: {len(results)} 只 | 最优: {results[0]['code'] if results else '无'}")
    return results


# ═══════════════════════════════════════════════
# 买入决策
# ═══════════════════════════════════════════════

def select_best_candidate(candidates: List[Dict]) -> Optional[Dict]:
    """
    从候选股中选出最优（评分最高），满仓买入
    多股并列时按综合评分选最优1只
    """
    if not candidates:
        return None
    return candidates[0]  # 已按score降序排列


# ═══════════════════════════════════════════════
# 卖出条件判断（次日早盘）
# ═══════════════════════════════════════════════

def should_sell(
    position: dict,
    current_price: float,
    highest_today: float,
    index_change_pct: float = 0.0,
) -> dict:
    """
    判断是否应该卖出持仓
    position: {'stock_code', 'avg_cost', 'shares', ...}
    current_price: 当前最新价
    highest_today: 今日最高价（用于从高点回落计算）
    返回: {'sell': bool, 'reason': str, 'urgency': 'normal'/'urgent'}
    """
    avg_cost = position['avg_cost']
    if avg_cost <= 0 or current_price <= 0:
        return {'sell': False, 'reason': '价格数据异常', 'urgency': 'normal'}

    gain_pct = (current_price - avg_cost) / avg_cost * 100
    peak_drop = (current_price - highest_today) / highest_today * 100 if highest_today > 0 else 0

    # ① 止损：-2%（无条件，最高优先级）
    if gain_pct <= -2.0:
        return {'sell': True, 'reason': f'止损触发 {gain_pct:.2f}%（阈值-2%）', 'urgency': 'urgent'}

    # ② 止盈：+5%~8% 冲高即走
    if gain_pct >= 5.0:
        return {'sell': True, 'reason': f'止盈触发 {gain_pct:.2f}%（目标+5%~8%）', 'urgency': 'normal'}

    # ③ 从最高点回落 -2%
    if highest_today > avg_cost and peak_drop <= -2.0:
        return {'sell': True, 'reason': f'高点回落 {peak_drop:.2f}%（阈值-2%）', 'urgency': 'urgent'}

    # ④ RSI > 70（需额外查询，不在此函数中）
    rsi = position.get('current_rsi', 50)
    if rsi > 70:
        return {'sell': True, 'reason': f'RSI超买 {rsi:.1f}（阈值70）', 'urgency': 'normal'}

    # ⑤ 放量滞涨（涨幅<1%，成交量暴增）
    vol_ratio = position.get('current_vol_ratio', 1.0)
    if gain_pct < 1.0 and vol_ratio > 2.0:
        return {'sell': True, 'reason': f'放量滞涨 涨幅{gain_pct:.2f}% 量比{vol_ratio:.1f}x', 'urgency': 'normal'}

    # ⑥ 跌破分时均价线
    avg_price = position.get('current_avg_price', 0)
    if avg_price > 0 and current_price < avg_price:
        return {'sell': True, 'reason': f'跌破分时均价 {avg_price}', 'urgency': 'normal'}

    # 继续持有
    return {'sell': False, 'reason': f'持有观察 涨幅{gain_pct:.2f}%', 'urgency': 'normal'}


# ═══════════════════════════════════════════════
# 仓位计算
# ═══════════════════════════════════════════════

def calc_position_size(cash: float, price: float, commission_rate: float = 0.00026) -> dict:
    """
    计算满仓买入股数（考虑手续费，确保现金够用）
    返回 {'shares': 整手数, 'amount': 总金额, 'commission': 手续费, 'total_cost': 含费总成本}
    """
    if price <= 0 or cash <= 0:
        return {'shares': 0, 'amount': 0, 'commission': 0, 'total_cost': 0}

    # 迭代计算（手续费会影响可买股数）
    for _ in range(3):
        raw_shares = int(cash / price / 100) * 100
        if raw_shares <= 0:
            break
        amount = raw_shares * price
        commission = max(amount * commission_rate, 5.0)
        total_cost = amount + commission
        if total_cost <= cash:
            return {
                'shares': raw_shares,
                'amount': round(amount, 2),
                'commission': round(commission, 2),
                'total_cost': round(total_cost, 2)
            }
        # 回退一手
        raw_shares -= 100
        if raw_shares <= 0:
            break

    return {'shares': 0, 'amount': 0, 'commission': 0, 'total_cost': 0}
