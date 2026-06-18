"""
一夜持股法策略模块
===================
尾盘14:50-14:55买入，次日早盘09:30-10:30卖出
超短线一夜持股，-2%止损，+5%~8%止盈

v3.1 数据源迁移: 东方财富全线断开 → 纯腾讯API
  - 选股扫描: 腾讯批量行情(全市场) + 腾讯K线(RSI)
  - 实时行情: 腾讯qt.gtimg.cn
  - 日K线: 腾讯web.ifzq.gtimg.cn
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies import BaseStrategy, StrategyRegistry
from datetime import datetime, timezone, timedelta, time as t_time
import numpy as np
import requests
import time as pytime


class OvernightStrategy(BaseStrategy):
    """一夜持股法策略"""
    
    name = "一夜持股法"
    strategy_type = "overnight"
    description = "尾盘14:50-14:55买入，次日早盘09:30-10:30卖出，超短线一夜持股"
    
    def __init__(self, strategy_id: int, config: dict = None):
        super().__init__(strategy_id, config)
        self.config = {
            'rise_min': 3.0,          # 最小涨幅%
            'rise_max': 10.0,         # 最大涨幅%
            'rsi_min': 40,            # RSI下限
            'rsi_max': 80,            # RSI上限
            'turnover_min': 2.0,      # 换手率下限%
            'turnover_max': 15.0,     # 换手率上限%
            'volume_ratio_min': 1.2,  # 成交量放大倍数
            'market_cap_min': 30,     # 流通市值下限(亿)
            'market_cap_max': 500,    # 流通市值上限(亿)
            'stop_loss': -2.0,        # 止损%
            'take_profit_min': 4.0,   # 止盈下限%
            'take_profit_max': 10.0,  # 止盈上限%
            'max_positions': 3,       # 最多同时持3只
            'position_size': 30000,   # 单票建仓¥30,000
            'buy_time_start': '14:50',
            'buy_time_end': '14:55',
            'sell_time_start': '09:30',
            'sell_time_end': '10:30',
            ** (config or {})
        }
    
    def is_buy_time(self) -> bool:
        bj = self.get_bj_time()
        now = bj.time()
        start = t_time(14, 50)
        end = t_time(14, 55)
        return start <= now <= end
    
    def is_sell_time(self) -> bool:
        bj = self.get_bj_time()
        now = bj.time()
        start = t_time(9, 30)
        end = t_time(10, 30)
        return start <= now <= end
    
    def _get_tencent_quote(self, code: str) -> dict:
        """腾讯实时行情"""
        try:
            prefix = 'sh' if code.startswith(('6', '5')) else 'sz'
            r = requests.get(f'https://qt.gtimg.cn/q={prefix}{code}', 
                             headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
            fields = r.text.split('="')[1].strip('"').split('~')
            if len(fields) < 50: return {}
            return {
                'name': fields[1],
                'price': float(fields[3]) if fields[3] != '-' else 0,
                'change_pct': float(fields[32]) if fields[32] != '-' else 0,
                'turnover': float(fields[38]) if fields[38] != '-' else 0,
                'volume_ratio': float(fields[49]) if len(fields) > 49 and fields[49] != '-' else 1.0,
                'pe': float(fields[39]) if fields[39] != '-' else 0,
            }
        except Exception:
            return {}
    
    def _get_kline(self, code: str, days: int = 60) -> list:
        """日K线（腾讯API）"""
        prefix = 'sh' if code.startswith(('6', '5')) else 'sz'
        for retry in range(3):
            try:
                r = requests.get(
                    f'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={prefix}{code},day,,,{days},qfq',
                    headers={'User-Agent': 'Mozilla/5.0'}, timeout=10
                )
                data = r.json()
                kd = data.get('data', {}).get(f'{prefix}{code}', {})
                klines = kd.get('qfqday') or kd.get('day')
                if klines: return klines
            except Exception:
                pytime.sleep(1)
        return []
    
    def _calc_rsi(self, closes: list, period: int = 14) -> float:
        if len(closes) < period + 1:
            return 50.0
        deltas = np.diff(closes[-period-1:])
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = np.mean(gains)
        avg_loss = np.mean(losses)
        if avg_loss == 0: return 100.0
        return 100 - (100 / (1 + avg_gain / avg_loss))
    
    def _get_market_index(self) -> dict:
        try:
            r = requests.get('https://qt.gtimg.cn/q=sh000001', 
                             headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
            fields = r.text.split('="')[1].strip('"').split('~')
            return {
                'name': fields[1],
                'price': float(fields[3]) if fields[3] != '-' else 0,
                'change_pct': float(fields[32]) if fields[32] != '-' else 0,
            }
        except Exception:
            return {'name': '上证指数', 'price': 0, 'change_pct': 0}
    
    def _scan_tencent_batch(self, codes: list) -> list:
        """腾讯批量行情扫描（一次最多500只）
        
        腾讯行情字段（按~分隔）:
        [1]=名称 [2]=代码 [3]=现价 [32]=涨跌幅 [38]=换手率 [46]=流通市值 [49]=量比
        """
        all_stocks = []
        for start in range(0, len(codes), 500):
            batch = codes[start:start+500]
            try:
                url = f'https://qt.gtimg.cn/q={",".join(batch)}'
                r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=20)
                for item in r.text.strip().split(';'):
                    if '="' not in item:
                        continue
                    try:
                        fields = item.split('="')[1].strip('"').split('~')
                        if len(fields) < 50:
                            continue
                        name = fields[1]
                        code = fields[2]
                        price = float(fields[3]) if fields[3] not in ('', '-') else 0
                        change_pct = float(fields[32]) if fields[32] not in ('', '-') else 0
                        turnover = float(fields[38]) if fields[38] not in ('', '-') else 0
                        vol_ratio = float(fields[49]) if len(fields) > 49 and fields[49] not in ('', '-') else 1.0
                        mkt_cap_str = fields[44] if len(fields) > 44 and fields[44] not in ('', '-') else '0'
                        
                        # 排除无效或占位数据
                        if price == 0 or code == fields[1] or code == name:
                            continue
                        
                        all_stocks.append({
                            'name': name, 'code': code, 'price': price,
                            'change_pct': change_pct, 'turnover': turnover,
                            'volume_ratio': vol_ratio,
                            'market_cap': float(mkt_cap_str) / 1e8 if mkt_cap_str not in ('0', '-') else 0,
                        })
                    except (IndexError, ValueError):
                        continue
            except Exception:
                continue
        return all_stocks
    
    def scan_stocks(self) -> list:
        """尾盘选股扫描（腾讯全量扫描）
        
        流程：
        1. 生成全A股代码 → 腾讯批量行情扫描
        2. 涨幅/换手率/量比/ST 初步过滤
        3. 腾讯K线计算RSI → 精细过滤
        4. 综合评分排序
        """
        cfg = self.config
        index = self._get_market_index()
        
        # 生成全市场代码（覆盖沪深北主要板块）
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
        
        # 批量扫描全市场
        all_stocks = self._scan_tencent_batch(codes)
        if not all_stocks:
            return []
        
        # 初步过滤
        candidates = []
        for s in all_stocks:
            pct = s['change_pct']
            name = s['name']
            code = s['code']
            
            if 'ST' in name or '*ST' in name:
                continue
            if code.startswith('8') or code.startswith('4'):
                continue
            if not (cfg['rise_min'] <= pct <= cfg['rise_max']):
                continue
            if not (cfg['turnover_min'] <= s['turnover'] <= cfg['turnover_max']):
                continue
            if s['volume_ratio'] < cfg['volume_ratio_min']:
                continue
            candidates.append(s)
        
        # RSI过滤+评分
        results = []
        for s in candidates:
            klines = self._get_kline(s['code'], 30)
            if len(klines) < 15:
                continue
            closes = [float(k[2]) for k in klines]
            rsi = self._calc_rsi(closes, 14)
            
            if not (cfg['rsi_min'] <= rsi <= cfg['rsi_max']):
                continue
            
            score = (s['change_pct'] - cfg['rise_min']) * 2
            score += min(s['turnover'], 10) * 0.5
            score += (80 - rsi) * 0.5
            score += min(s['volume_ratio'] / cfg['volume_ratio_min'], 3) * 5
            if index.get('change_pct', 0) and s['change_pct'] > index['change_pct']:
                score += 10
            
            results.append({
                'code': s['code'], 'name': s['name'],
                'price': s['price'], 'change_pct': s['change_pct'],
                'turnover': s['turnover'], 'market_cap': round(s['market_cap'], 1),
                'rsi': round(rsi, 1), 'volume_ratio': round(s['volume_ratio'], 2),
                'score': round(score, 1),
            })
        
        results.sort(key=lambda x: x['score'], reverse=True)
        return results
    
    def get_buy_criteria_description(self) -> str:
        cfg = self.config
        return (
            f"涨幅{cfg['rise_min']}%-{cfg['rise_max']}%、"
            f"成交量>{cfg['volume_ratio_min']}x、"
            f"换手率{cfg['turnover_min']}%-{cfg['turnover_max']}%、"
            f"流通市值{cfg['market_cap_min']}-{cfg['market_cap_max']}亿、"
            f"RSI < {cfg['rsi_max']}、"
            f"站上分时均价线、强于大盘"
        )


# 注册策略
StrategyRegistry.register(OvernightStrategy)
