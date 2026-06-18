"""
趋势跟踪策略 v2.0 — 多因子趋势评分系统
=======================================
核心框架：多因子趋势评分系统 + 热点板块驱动

v2.0 升级:
- 热点板块识别（stock_board_industry_summary_ths）
- 强势股池过滤（stock_zt_pool_strong_em/previous_em）
- 多因子趋势评分（动量30%+成交量20%+MA趋势20%+MACD15%+RSI15%）
- ATR动态止损（代替固定-5%）
- 涨停因子（涨停次日不追，涨停后3-5天企稳买入）
- K线突破形态确认
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies import BaseStrategy, StrategyRegistry
from datetime import datetime, timezone, timedelta, time as t_time
import akshare as ak
import pandas as pd
import numpy as np
import requests
import time as pytime
import json

# 信号数据服务（资金流+龙虎榜验证）
try:
    import sys as _sys
    import os as _os
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    from services.signal import fund_flow_trend, dragon_tiger_check
    SIGNAL_AVAILABLE = True
except ImportError:
    SIGNAL_AVAILABLE = False


class TrendFollowingStrategy(BaseStrategy):
    """趋势跟踪策略 v2.0 — 多因子趋势评分"""
    
    name = "趋势跟踪"
    strategy_type = "trend"
    description = "多因子趋势评分+热点板块驱动, ATR动态止损, 持股1-2周"
    
    def __init__(self, strategy_id: int, config: dict = None):
        super().__init__(strategy_id, config)
        self.config = {
            # 选股参数
            'min_days_since_limitup': 3,   # 涨停后至少等N天
            'max_recent_pct': 30,          # 最近5日涨幅上限（↑原18，牛市强势股5日涨20%+很常见）
            'min_recent_pct': 3,           # 最近5日涨幅下限（要有趋势）
            
            # 多因子权重
            'w_momentum': 30,              # 动量（近期涨幅）
            'w_volume': 20,                # 成交量（放量确认）
            'w_ma_trend': 20,              # 均线趋势
            'w_macd': 15,                  # MACD信号
            'w_rsi': 15,                   # RSI位置
            
            # 趋势确认
            'volume_ratio_min': 1.0,       # 放量倍数（放宽至1.0，允许缩量趋势如杰瑞股份）
            'rsi_max': 92,                 # RSI上限（↑原82，牛市龙头RSI常在85-92运行）
            'rsi_min': 40,                 # RSI下限（有动力）
            
            # 退出规则
            'stop_loss': -6.0,             # 止损%（ATR动态调整，此为基准）
            'take_profit': 12.0,           # 止盈%
            'max_hold_days': 14,           # 最长持有天数
            'peak_retreat': -4.0,          # 从高点回撤%
            
            # 热点板块
            'hot_board_top_n': 5,          # 取前N个热门板块
            ** (config or {})
        }
    
    def is_trading_time(self) -> bool:
        bj = self.get_bj_time()
        now = bj.time()
        return t_time(9, 30) <= now <= t_time(15, 0)
    
    # ═══════════════════════════════════════
    # 数据获取
    # ═══════════════════════════════════════
    
    def _get_tencent_quote(self, code: str) -> dict:
        try:
            prefix = "sh" if code.startswith(('6', '5')) else "sz"
            r = requests.get(
                f"https://qt.gtimg.cn/q={prefix}{code}",
                headers={'User-Agent': 'Mozilla/5.0'},
                timeout=5
            )
            fields = r.text.split('="')[1].strip('"').split('~')
            if len(fields) < 40:
                return {}
            return {
                'name': fields[1],
                'price': float(fields[3]) if fields[3] != '-' else 0,
                'change_pct': float(fields[32]) if fields[32] != '-' else 0,
                'turnover': float(fields[38]) if fields[38] != '-' else 0,
                'volume_ratio': float(fields[49]) if len(fields) > 49 and fields[49] != '-' else 1.0,
                'pe': float(fields[39]) if fields[39] != '-' else 0,
                'amount': float(fields[37]) if len(fields) > 37 and fields[37] != '-' else 0,
            }
        except Exception:
            return {}
    
    def _get_kline(self, code: str, days: int = 120) -> pd.DataFrame:
        """获取日K线（腾讯API，替代akshare）"""
        prefix = "sh" if code.startswith(('6', '5')) else "sz"
        for retry in range(3):
            try:
                r = requests.get(
                    f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={prefix}{code},day,,,{days},qfq",
                    headers={'User-Agent': 'Mozilla/5.0'},
                    timeout=10
                )
                data = r.json()
                kd = data.get('data', {}).get(f'{prefix}{code}', {})
                klines = kd.get('qfqday') or kd.get('day')
                if not klines:
                    continue
                
                # 解析为DataFrame格式（兼容原有评分逻辑）
                rows = []
                for k in klines:
                    parts = k if isinstance(k, list) else k.split('/')
                    # parts: [日期, 开盘, 收盘, 最高, 最低, 成交量]
                    rows.append({
                        '日期': parts[0],
                        '开盘': float(parts[1]),
                        '收盘': float(parts[2]),
                        '最高': float(parts[3]),
                        '最低': float(parts[4]),
                        '成交量': float(parts[5]),
                    })
                df = pd.DataFrame(rows)
                df['日期'] = pd.to_datetime(df['日期'])
                df = df.sort_values('日期')
                df = df.tail(days).copy()
                return df
            except Exception:
                pytime.sleep(1)
                continue
        return pd.DataFrame()
    
    def _calc_atr(self, df: pd.DataFrame, period: int = 14) -> float:
        """计算ATR（平均真实波幅）"""
        if len(df) < period + 1:
            return 0
        high, low, close = df['最高'].values, df['最低'].values, df['收盘'].values
        tr = np.maximum(
            high[1:] - low[1:],
            np.maximum(
                np.abs(high[1:] - close[:-1]),
                np.abs(low[1:] - close[:-1])
            )
        )
        return float(np.mean(tr[-period:]))
    
    def _calc_rsi(self, prices, period=14):
        if len(prices) < period + 1:
            return 50.0
        deltas = np.diff(prices[-period-1:])
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = np.mean(gains)
        avg_loss = np.mean(losses)
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))
    
    def _get_hot_boards(self) -> list:
        """热门板块（腾讯不提供板块数据，返回空）"""
        return []
    
    def _get_hot_stocks_from_pool(self) -> list:
        """从全市场腾讯批量查询获取热门候选股票"""
        candidates = []
        
        # 复用腾讯批量扫描逻辑
        codes = []
        for prefix in ['sh600', 'sh601', 'sh603', 'sh605']:
            codes.extend([f'{prefix}{i:0>3d}' for i in range(1000)])
        codes.extend([f'sh688{i:0>3d}' for i in range(600)])
        for prefix in ['sz000', 'sz001']:
            codes.extend([f'{prefix}{i:0>3d}' for i in range(1000)])
        for prefix in ['sz002', 'sz003']:
            codes.extend([f'{prefix}{i:0>3d}' for i in range(1000)])
        for prefix in ['sz300', 'sz301']:
            codes.extend([f'{prefix}{i:0>3d}' for i in range(1000)])
        
        headers = {'User-Agent': 'Mozilla/5.0'}
        for start in range(0, len(codes), 500):
            batch = codes[start:start+500]
            try:
                url = f'https://qt.gtimg.cn/q={",".join(batch)}'
                r = requests.get(url, headers=headers, timeout=20)
                for item in r.text.strip().split(';'):
                    if '="' not in item: continue
                    try:
                        fields = item.split('="')[1].strip('"').split('~')
                        if len(fields) < 50: continue
                        name = fields[1]; code = fields[2]
                        pct = float(fields[32]) if fields[32] not in ('', '-') else 0
                        turnover = float(fields[38]) if fields[38] not in ('', '-') else 0
                        price = float(fields[3]) if fields[3] not in ('', '-') else 0
                        if price == 0 or code == fields[1]: continue
                        if 'ST' in name or '*ST' in name: continue
                        # 候选池：涨幅<18%（含涨停），换手率不限
                        if 0 <= pct <= 18:
                            candidates.append({'code': code, 'name': name, 'pct': pct, 'turnover': turnover})
                    except: continue
            except: continue
        
        return candidates
    
    # ═══════════════════════════════════════
    # 多因子趋势评分
    # ═══════════════════════════════════════
    
    def _score_momentum(self, df: pd.DataFrame) -> tuple:
        """动量评分（满分30）"""
        cfg = self.config
        closes = df['收盘'].values
        if len(closes) < 5:
            return 0, "数据不足"
        
        # 5日涨幅
        pct_5d = (closes[-1] - closes[-6]) / closes[-6] * 100 if len(closes) > 6 else 0
        # 10日涨幅
        pct_10d = (closes[-1] - closes[-11]) / closes[-11] * 100 if len(closes) > 11 else 0
        
        if pct_5d < cfg['min_recent_pct']:
            return 0, f"5日涨幅{pct_5d:.1f}% < {cfg['min_recent_pct']}%，动量不足"
        if pct_5d > cfg['max_recent_pct']:
            return 0, f"5日涨幅{pct_5d:.1f}% > {cfg['max_recent_pct']}%，追高风险"
        
        # 动量持续性（10日涨幅合理）
        if pct_5d >= 8 and pct_10d >= 10 and pct_5d < pct_10d:
            score = 28
            desc = f"强势持续 5日+{pct_5d:.1f}%/10日+{pct_10d:.1f}% ⭐"
        elif pct_5d >= 5:
            score = 22
            desc = f"稳健上涨 5日+{pct_5d:.1f}% ✅"
        elif pct_5d >= 3:
            score = 15
            desc = f"温和上涨 5日+{pct_5d:.1f}% ⚠️"
        else:
            score = 8
            desc = f"弱势 5日+{pct_5d:.1f}%"
        
        return min(score, 30), desc
    
    def _score_volume(self, df: pd.DataFrame) -> tuple:
        """成交量评分（满分20）"""
        cfg = self.config
        volumes = df['成交量'].values
        closes = df['收盘'].values
        
        if len(volumes) < 10:
            return 0, "数据不足"
        
        vol_ma5 = pd.Series(volumes).rolling(5).mean().values
        latest_vol = volumes[-1]
        latest_vol_ma = vol_ma5[-1] if not np.isnan(vol_ma5[-1]) else 0
        
        if latest_vol_ma <= 0:
            return 5, "成交量数据异常"
        
        vol_ratio = latest_vol / latest_vol_ma
        
        if vol_ratio >= 2.0:
            score = 20
            desc = f"巨量放大 {vol_ratio:.1f}x ⭐"
        elif vol_ratio >= cfg['volume_ratio_min']:
            score = 15
            desc = f"温和放量 {vol_ratio:.1f}x ✅"
        elif vol_ratio >= 1.0:
            score = 8
            desc = f"量能正常 {vol_ratio:.1f}x"
        else:
            score = 3
            desc = f"缩量 {vol_ratio:.1f}x ⚠️"
        
        # 最近3天放量趋势加分
        if len(volumes) >= 5:
            recent_ratios = [volumes[-i] / vol_ma5[-i] if not np.isnan(vol_ma5[-i]) and vol_ma5[-i] > 0 else 1 for i in range(1, 4)]
            increasing = sum(1 for i in range(1, len(recent_ratios)) if recent_ratios[i] > recent_ratios[i-1])
            if increasing >= 2:
                score += 3
                desc += " 📈 放量趋势"
        
        return min(score, 23), desc
    
    def _score_ma_trend(self, df: pd.DataFrame) -> tuple:
        """均线趋势评分（满分20）"""
        closes = df['收盘'].values
        if len(closes) < 60:
            return 5, "数据不足"
        
        # 计算均线
        closes_series = pd.Series(closes)
        ma5 = closes_series.rolling(5).mean().values
        ma10 = closes_series.rolling(10).mean().values
        ma20 = closes_series.rolling(20).mean().values
        ma60 = closes_series.rolling(60).mean().values
        
        score = 0
        items = []
        
        # 收盘价站上5日线
        if closes[-1] > ma5[-1]:
            score += 3; items.append("站上5日线")
        # 5日 > 10日（短线上涨）
        if ma5[-1] > ma10[-1]:
            score += 4; items.append("5日>10日")
        # 20日 > 60日（多头排列）
        if ma20[-1] > ma60[-1]:
            score += 5; items.append("20日>60日多头")
        # 价格高于20日线
        if closes[-1] > ma20[-1]:
            score += 3; items.append("价在20日线上")
        # 均线发散向上
        if len(closes) > 20:
            ma20_slope = (ma20[-1] - ma20[-5]) / ma20[-5] * 100
            if ma20_slope > 1:
                score += 5; items.append(f"均线上扬+{ma20_slope:.1f}%")
        
        return score, "；".join(items) if items else "均线走弱"
    
    def _score_macd(self, df: pd.DataFrame) -> tuple:
        """MACD评分（满分15）"""
        closes = df['收盘'].values
        if len(closes) < 35:
            return 5, "数据不足"
        
        # EMA计算
        ema12 = pd.Series(closes).ewm(span=12).mean().values
        ema26 = pd.Series(closes).ewm(span=26).mean().values
        dif = ema12 - ema26
        dea = pd.Series(dif).ewm(span=9).mean().values
        macd_bar = 2 * (dif - dea)
        
        score = 0
        items = []
        
        # DIF > DEA（金叉/多头）
        if dif[-1] > dea[-1]:
            score += 5; items.append("DIF>DEA多头")
        # MACD柱为正
        if macd_bar[-1] > 0:
            score += 4; items.append("红柱")
        # DIF在零轴上方
        if dif[-1] > 0:
            score += 3; items.append("DIF>0强势")
        # MACD柱放大（动能增强）
        if len(macd_bar) > 2 and macd_bar[-1] > macd_bar[-2]:
            score += 3; items.append("动能增强")
        
        return score, "；".join(items) if items else "MACD偏弱"
    
    def _score_rsi(self, df: pd.DataFrame) -> tuple:
        """RSI评分（满分15）"""
        cfg = self.config
        closes = df['收盘'].values
        rsi = self._calc_rsi(closes)
        
        if rsi >= 95:
            return 0, f"RSI={rsi:.0f} ❌ 严重超买"
        elif rsi >= cfg['rsi_max']:
            return 0, f"RSI={rsi:.0f} ❌ 过热（>{cfg['rsi_max']}）"
        elif rsi >= 70:
            score = 15
            desc = f"RSI={rsi:.0f} ⭐ 强势区间"
        elif rsi >= 55:
            score = 12
            desc = f"RSI={rsi:.0f} ✅ 偏强"
        elif rsi >= cfg['rsi_min']:
            score = 8
            desc = f"RSI={rsi:.0f} ⚠️ 中性"
        else:
            score = 3
            desc = f"RSI={rsi:.0f} ❌ 偏弱"
        
        return score, desc
    
    # ═══════════════════════════════════════
    # 核心评估
    # ═══════════════════════════════════════
    
    def check_trend_signal(self, code: str) -> dict:
        """完整趋势信号评估"""
        # 获取K线
        df = self._get_kline(code)
        if df.empty or len(df) < 60:
            return {'buy_signal': False, 'reason': '数据不足'}
        
        closes = df['收盘'].values
        
        # 多因子评分
        mom_score, mom_desc = self._score_momentum(df)
        vol_score, vol_desc = self._score_volume(df)
        ma_score, ma_desc = self._score_ma_trend(df)
        macd_score, macd_desc = self._score_macd(df)
        rsi_score, rsi_desc = self._score_rsi(df)
        
        total_score = mom_score + vol_score + ma_score + macd_score + rsi_score
        
        # K线形态确认（收盘站稳+连续上涨）
        kline_confirm = False
        if len(closes) >= 5:
            # 条件A：最近3天有2天收涨
            up_days = sum(1 for i in range(-3, 0) if closes[i] > closes[i-1])
            # 条件B：最近3天收盘价都站在5日线上（趋势稳定）
            ma5_recent = pd.Series(closes).rolling(5).mean().values
            above_ma5_3d = len(closes) >= 5 and all(closes[-i] > ma5_recent[-i] for i in range(1, 4))
            if up_days >= 2 or above_ma5_3d:
                kline_confirm = True
        
        # ATR（用于动态止损）
        atr = self._calc_atr(df)
        current_price = closes[-1]
        atr_pct = (atr / current_price * 100) if current_price > 0 else 0
        
        # 热门板块匹配
        hot_boards = self._get_hot_boards()
        
        # 涨停冷却检查
        recent_limits = 0
        recent_high = np.max(closes[-10:])
        for i in range(-10, -1):
            if len(closes) > abs(i) and i < -1:
                day_pct = (closes[i] - closes[i-1]) / closes[i-1] * 100
                if day_pct >= 9.5:
                    recent_limits += 1
        
        days_since_limit = 99
        if recent_limits > 0:
            for i in range(-20, 0):
                if len(closes) > abs(i) and i < -1:
                    day_pct = (closes[i] - closes[i-1]) / closes[i-1] * 100
                    if day_pct >= 9.5:
                        days_since_limit = abs(i) - 1
                        break
        
        # 涨停冷却判断
        limit_cool = days_since_limit >= self.config['min_days_since_limitup']
        
        # 买入判断
        buy_signal = (
            total_score >= 55 and
            kline_confirm and
            rsi_score > 0 and  # RSI不过热
            limit_cool and
            mom_score > 0       # 有动量
        )
        
        # === 信号层验证（新增） ===
        fund_trend_info = {'net_5d_wan': 0, 'consecutive_inflow': 0, 'trend': 'unknown'}
        dragon_info = {'on_board': False, 'score': 0, 'institution_net_wan': 0}
        signal_bonus = 0
        
        if SIGNAL_AVAILABLE and buy_signal:
            try:
                # 资金流趋势验证（近5日主力净流入）
                fund_trend_info = fund_flow_trend(code, days=5)
                if fund_trend_info['trend'] == 'strong':
                    signal_bonus += 10
                elif fund_trend_info['trend'] == 'neutral':
                    signal_bonus += 5
                elif fund_trend_info['trend'] == 'weak':
                    # 资金流出时降分（取消绝对否决，强势股高换手率下适度流出是正常的）
                    net = fund_trend_info.get('net_5d_wan', 0)
                    if net < -50000:  # 超5亿流出，严重降分
                        signal_bonus -= 10
                    elif net < -10000:  # 1-5亿流出，中度降分
                        signal_bonus -= 5
                    else:  # 轻度流出
                        signal_bonus -= 2
            except Exception:
                pass
            
            try:
                # 龙虎榜验证（机构买入=强确认）
                dragon_info = dragon_tiger_check(code)
                if dragon_info.get('institution_net_wan', 0) > 1000:
                    signal_bonus += 10  # 机构大买
                elif dragon_info.get('on_board'):
                    signal_bonus += 3   # 上榜但无机构
            except Exception:
                pass
        
        total_score += signal_bonus
        
        # 动态止损价
        dynamic_stop = current_price * (1 + self.config['stop_loss'] / 100) if buy_signal else 0
        
        return {
            'buy_signal': buy_signal,
            'total_score': total_score,
            'max_score': 120,  # 基础100 + 信号层加分最高20
            'score_breakdown': {
                'momentum': {'score': mom_score, 'max': 30, 'desc': mom_desc},
                'volume': {'score': vol_score, 'max': 23, 'desc': vol_desc},
                'ma_trend': {'score': ma_score, 'max': 20, 'desc': ma_desc},
                'macd': {'score': macd_score, 'max': 15, 'desc': macd_desc},
                'rsi': {'score': rsi_score, 'max': 15, 'desc': rsi_desc},
                'signal_layer': {'score': signal_bonus, 'max': 20, 'desc': self._format_signal_desc(fund_trend_info, dragon_info)},
            },
            'metrics': {
                'current_price': float(current_price),
                'atr': float(atr),
                'atr_pct': round(atr_pct, 2),
                'hot_boards': hot_boards[:3] if hot_boards else [],
                'recent_limits': recent_limits,
                'days_since_limit': days_since_limit,
                'kline_confirm': kline_confirm,
                'dynamic_stop_price': round(dynamic_stop, 2),
                'fund_5d_net_wan': fund_trend_info.get('net_5d_wan', 0),
                'fund_trend': fund_trend_info.get('trend', 'unknown'),
                'dragon_tiger': dragon_info.get('on_board', False),
                'institution_net_wan': dragon_info.get('institution_net_wan', 0),
            },
            'reason': self._format_signal_reason(
                total_score, mom_desc, vol_desc, ma_desc,
                macd_desc, rsi_desc, hot_boards, kline_confirm
            ),
        }
    
    def _format_signal_reason(self, score, *descs, hot_boards=None, kline_confirm=False) -> str:
        parts = [f"评分{score}分"]
        for d in descs:
            if d:
                parts.append(d)
        if hot_boards:
            parts.append(f"热点板块:{','.join(hot_boards[:3])}")
        if kline_confirm:
            parts.append("K线确认")
        return " | ".join(parts[:6])
    
    def _format_signal_desc(self, fund_info: dict, dragon_info: dict) -> str:
        """格式化信号层描述"""
        parts = []
        trend = fund_info.get('trend', 'unknown')
        net = fund_info.get('net_5d_wan', 0)
        if trend == 'strong':
            parts.append(f"资金强势(5日净流入{net:.0f}万)")
        elif trend == 'neutral':
            parts.append(f"资金中性({net:.0f}万)")
        elif trend == 'weak':
            parts.append(f"资金流出({net:.0f}万)⚠️")
        
        if dragon_info.get('on_board'):
            inst = dragon_info.get('institution_net_wan', 0)
            if inst > 0:
                parts.append(f"龙虎榜+机构买{inst:.0f}万")
            else:
                parts.append("龙虎榜上榜")
        
        return "；".join(parts) if parts else "无信号数据"
    
    # ═══════════════════════════════════════
    # 大盘环境过滤
    # ═══════════════════════════════════════
    
    def _check_market_environment(self) -> bool:
        """大盘环境检查：沪指站在5日线上方才允许开新仓
        
        2026-05-29校准：震荡市中趋势策略容易两面打脸，
        加入大盘趋势过滤，沪指破MA5时不开新仓。
        """
        try:
            resp = requests.get('http://localhost/api/index', timeout=10)
            if resp.status_code != 200:
                # API失败时保守处理：不开仓
                return False
            data = resp.json()
            # 找沪指数据
            sh_index = None
            if isinstance(data, list):
                for item in data:
                    if item.get('code') in ('000001', 'sh000001', '1.000001'):
                        sh_index = item
                        break
                if not sh_index and data:
                    sh_index = data[0]  # 默认取第一个
            elif isinstance(data, dict):
                sh_index = data
            
            if not sh_index:
                return False
            
            price = float(sh_index.get('price', 0))
            ma5 = float(sh_index.get('ma5', 0))
            
            if price <= 0 or ma5 <= 0:
                return False
            
            if price < ma5:
                # 沪指在MA5下方，不开新仓
                return False
            
            return True
        except Exception:
            # 异常时保守处理
            return False
    
    # ═══════════════════════════════════════
    # 扫描候选
    # ═══════════════════════════════════════
    
    def scan_stocks(self) -> list:
        """扫描市场，返回最佳候选"""
        # 2026-05-29校准：大盘环境过滤，沪指破5日线时不开新仓
        if not self._check_market_environment():
            return []
        
        candidates = self._get_hot_stocks_from_pool()
        if not candidates:
            return []
        
        results = []
        for c in candidates[:20]:  # 最多评20只
            signal = self.check_trend_signal(c['code'])
            if signal['buy_signal']:
                results.append({
                    'code': c['code'],
                    'name': self._get_tencent_quote(c['code']).get('name', c.get('name', '')),
                    'score': signal['total_score'],
                    'signal': signal,
                })
            pytime.sleep(0.5)  # API限流
        
        # 按评分排序
        results.sort(key=lambda x: x['score'], reverse=True)
        return results[:3]  # 最多返回3只
    
    # ═══════════════════════════════════════
    # 退出决策
    # ═══════════════════════════════════════
    
    def should_sell(self, code: str, cost_price: float, current_price: float,
                    highest_since_buy: float, hold_days: int) -> tuple:
        """多维度卖出决策"""
        cfg = self.config
        profit_pct = (current_price - cost_price) / cost_price * 100
        peak_retreat = (current_price - highest_since_buy) / highest_since_buy * 100 if highest_since_buy > cost_price else 0
        
        # 保本机制：浮盈曾超+5%后，止损线上移到成本价
        # 一旦赚过5%，最差也要保本出局，不允许从盈利变亏损
        ever_profitable_5pct = highest_since_buy > cost_price * 1.05
        if ever_profitable_5pct and profit_pct <= 0:
            return True, f"保本止损：曾盈利超5%（高点{highest_since_buy:.2f}），现回落至成本线（{profit_pct:+.1f}%）"
        
        # 止损（无条件）—— 仅在未触发保本机制时生效
        if profit_pct <= cfg['stop_loss']:
            return True, f"止损触发：{profit_pct:.1f}%（≤{cfg['stop_loss']}%）"
        
        # 止盈
        if profit_pct >= cfg['take_profit']:
            return True, f"止盈触发：+{profit_pct:.1f}%（≥+{cfg['take_profit']}%）"
        
        # 从高点回撤
        if peak_retreat <= cfg['peak_retreat']:
            return True, f"高位回撤{peak_retreat:.1f}%（≤{cfg['peak_retreat']}%）"
        
        # 时间衰减：持仓超7天且从高点回落3%，说明动能衰竭
        if hold_days >= 7 and current_price < highest_since_buy * 0.97:
            return True, f"时间衰减：持仓{hold_days}天，从高点回落{((current_price - highest_since_buy) / highest_since_buy * 100):.1f}%，动能不足"
        
        # 超时
        if hold_days >= cfg['max_hold_days']:
            return True, f"超时卖出：已持有{hold_days}天"
        
        # 趋势反转（重新检查）
        if hold_days >= 5:
            signal = self.check_trend_signal(code)
            if not signal['buy_signal'] and signal['total_score'] < 40:
                return True, f"趋势转弱：评分{signal['total_score']}分"
        
        return False, ""


# 注册策略
StrategyRegistry.register(TrendFollowingStrategy)
