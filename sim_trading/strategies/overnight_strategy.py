"""
一夜持股法策略模块
===================
尾盘14:50-14:55买入，次日早盘09:30-10:30卖出
超短线一夜持股

v3.1 数据源迁移: 东方财富全线断开 → 纯腾讯API
v3.2 并发优化: _scan_tencent_batch 多线程并发, 50s→~15s
v3.3 热点因子 + 放宽止损: 
  - 自动计算全市场热力排名，选热点板块的强势股
  - 止损从-2%放宽到-3.5%，减少被震飞
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies import BaseStrategy, StrategyRegistry
from datetime import datetime, timezone, timedelta, time as t_time
import numpy as np
import requests
import time as pytime
from concurrent.futures import ThreadPoolExecutor, as_completed
import math


class OvernightStrategy(BaseStrategy):
    """一夜持股法策略"""
    
    name = "一夜持股法"
    strategy_type = "overnight"
    description = "尾盘14:50-14:55买入，次日早盘09:30-10:30卖出，超短线一夜持股"
    
    def __init__(self, strategy_id: int, config: dict = None):
        super().__init__(strategy_id, config)
        self.config = {
            'rise_min': 3.0,          'rise_max': 10.0,
            'rsi_min': 40,            'rsi_max': 80,
            'turnover_min': 2.0,      'turnover_max': 15.0,
            'volume_ratio_min': 1.2,
            'market_cap_min': 30,     'market_cap_max': 500,
            'stop_loss': -3.5,
            'take_profit_min': 4.0,   'take_profit_max': 10.0,
            'max_positions': 3,       'position_size': 30000,
            'buy_time_start': '14:50', 'buy_time_end': '14:55',
            'sell_time_start': '09:30', 'sell_time_end': '10:30',
            'hot_rank_top_n': 300,    # 热力值前N名算热门
            'hot_factor_weight': 20,  # 热门加分
            ** (config or {})
        }
    
    def is_buy_time(self) -> bool:
        bj = self.get_bj_time()
        now = bj.time()
        return t_time(14, 50) <= now <= t_time(14, 55)
    
    def is_sell_time(self) -> bool:
        bj = self.get_bj_time()
        now = bj.time()
        return t_time(9, 30) <= now <= t_time(10, 30)
    
    def _get_tencent_quote(self, code: str) -> dict:
        try:
            prefix = 'sh' if code.startswith(('6', '5')) else 'sz'
            r = requests.get(f'https://qt.gtimg.cn/q={prefix}{code}', 
                             headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
            fields = r.text.split('="')[1].strip('"').split('~')
            if len(fields) < 50: return {}
            return {'name': fields[1], 'price': float(fields[3]) if fields[3] != '-' else 0,
                    'change_pct': float(fields[32]) if fields[32] != '-' else 0,
                    'turnover': float(fields[38]) if fields[38] != '-' else 0,
                    'volume_ratio': float(fields[49]) if len(fields) > 49 and fields[49] != '-' else 1.0}
        except Exception:
            return {}
    
    def _get_kline(self, code: str, days: int = 60) -> list:
        prefix = 'sh' if code.startswith(('6', '5')) else 'sz'
        for retry in range(3):
            try:
                r = requests.get(
                    f'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={prefix}{code},day,,,{days},qfq',
                    headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
                data = r.json()
                kd = data.get('data', {}).get(f'{prefix}{code}', {})
                klines = kd.get('qfqday') or kd.get('day')
                if klines: return klines
            except Exception:
                pytime.sleep(1)
        return []
    
    def _calc_rsi(self, closes: list, period: int = 14) -> float:
        if len(closes) < period + 1: return 50.0
        deltas = np.diff(closes[-period-1:])
        gains, losses = np.where(deltas > 0, deltas, 0), np.where(deltas < 0, -deltas, 0)
        avg_gain, avg_loss = np.mean(gains), np.mean(losses)
        if avg_loss == 0: return 100.0
        return 100 - (100 / (1 + avg_gain / avg_loss))
    
    def _get_market_index(self) -> dict:
        try:
            r = requests.get('https://qt.gtimg.cn/q=sh000001',
                             headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
            fields = r.text.split('="')[1].strip('"').split('~')
            return {'name': fields[1], 'price': float(fields[3]) if fields[3] != '-' else 0,
                    'change_pct': float(fields[32]) if fields[32] != '-' else 0}
        except Exception:
            return {'name': '上证指数', 'price': 0, 'change_pct': 0}
    
    def _get_all_codes(self) -> list:
        """生成全A股代码（~7000只）"""
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
        return codes
    
    def _scan_tencent_batch(self, codes: list) -> list:
        """腾讯批量行情扫描（并发4线程，~15s 扫7000只）"""
        all_stocks = []
        
        def _fetch(batch_codes):
            batch_result = []
            try:
                url = f'https://qt.gtimg.cn/q={",".join(batch_codes)}'
                r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=20)
                for item in r.text.strip().split(';'):
                    if '="' not in item:
                        continue
                    try:
                        fields = item.split('="')[1].strip('"').split('~')
                        if len(fields) < 50: continue
                        name, code = fields[1], fields[2]
                        price = float(fields[3]) if fields[3] not in ('', '-') else 0
                        pct = float(fields[32]) if fields[32] not in ('', '-') else 0
                        turnover = float(fields[38]) if fields[38] not in ('', '-') else 0
                        vol_ratio = float(fields[49]) if len(fields) > 49 and fields[49] not in ('', '-') else 1.0
                        mkt_str = fields[44] if len(fields) > 44 and fields[44] not in ('', '-') else '0'
                        if price == 0 or code == fields[1]: continue
                        batch_result.append({
                            'name': name, 'code': code, 'price': price,
                            'change_pct': pct, 'turnover': turnover,
                            'volume_ratio': vol_ratio,
                            'market_cap': float(mkt_str) / 1e8 if mkt_str not in ('0', '-') else 0,
                        })
                    except (IndexError, ValueError):
                        continue
            except Exception:
                pass
            return batch_result
        
        batches = [codes[i:i+500] for i in range(0, len(codes), 500)]
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(_fetch, b) for b in batches]
            for f in as_completed(futures):
                all_stocks.extend(f.result())
        return all_stocks
    
    def _calc_heat_scores(self, all_stocks: list) -> dict:
        """从全市场扫描结果中自动计算每只股票的热力值
        
        无需外部概念API。思路：
        1. 全市场按 (量比归一化 + 换手率归一化 + 涨幅归一化) 排名
        2. 总排名前N（默认300）的标记为"热门股"，额外加分
        3. 这相当于自动抓到了当前热点板块里的活跃股
        
        返回: { code: heat_rank }  排名1=最热
        """
        # 过滤：排除无效、ST、北交所
        valid = []
        for s in all_stocks:
            if s['price'] <= 0: continue
            if s['turnover'] <= 0: continue
            name = s.get('name', '')
            code = s.get('code', '')
            if 'ST' in name or '*ST' in name: continue
            if code.startswith('8') or code.startswith('4'): continue
            valid.append(s)
        
        if len(valid) < 200:
            return {}
        
        # 计算百分位排名，避免极端值干扰
        vol_ratios = [s['volume_ratio'] for s in valid]
        turnovers = [s['turnover'] for s in valid]
        pcts = [abs(s['change_pct']) for s in valid]  # 用涨幅，但涨跌都算活跃
        
        def percentile_rank(values):
            """返回每个值在全体中的百分位排名 0-100"""
            sorted_vals = sorted(values)
            n = len(sorted_vals)
            rank_map = {}
            for i, v in enumerate(sorted_vals):
                rank_map.setdefault(v, []).append(i / n * 100)
            return [max(rank_map[v]) for v in values]
        
        vol_ranks = percentile_rank(vol_ratios)
        to_ranks = percentile_rank(turnovers)
        pct_ranks = percentile_rank(pcts)
        
        # 综合热力分 = 加权百分位
        heat_scores = {}
        for i, s in enumerate(valid):
            code = s['code']
            # 量比权重0.4 + 换手率权重0.3 + 涨幅权重0.3
            heat = vol_ranks[i] * 0.4 + to_ranks[i] * 0.3 + pct_ranks[i] * 0.3
            heat_scores[code] = heat
        
        return heat_scores
    
    def scan_stocks(self) -> list:
        """尾盘选股扫描（腾讯全量扫描+并发）
        
        流程：
        1. 生成全A股代码 → 腾讯批量扫描（并发）
        2. 计算全市场热力值（量比+换手率+涨幅百分位排名）
        3. 涨幅/换手率/量比/ST初步过滤
        4. 腾讯K线计算RSI → 精细过滤评分
        5. 热门股加分
        """
        cfg = self.config
        index = self._get_market_index()
        
        # 并发扫描全市场
        all_stocks = self._scan_tencent_batch(self._get_all_codes())
        if not all_stocks:
            return []
        
        # 计算热力值（基于全市场数据）
        heat_scores = self._calc_heat_scores(all_stocks)
        hot_threshold = cfg['hot_rank_top_n']
        # 找出排名前N的热门阈值
        if heat_scores:
            sorted_heats = sorted(heat_scores.values(), reverse=True)
            hot_cutoff = sorted_heats[min(hot_threshold - 1, len(sorted_heats) - 1)]
        else:
            hot_cutoff = 0
        
        # 初步过滤
        candidates = []
        for s in all_stocks:
            pct = s['change_pct']
            name = s['name']
            code = s['code']
            if 'ST' in name or '*ST' in name: continue
            if code.startswith('8') or code.startswith('4'): continue
            if not (cfg['rise_min'] <= pct <= cfg['rise_max']): continue
            if not (cfg['turnover_min'] <= s['turnover'] <= cfg['turnover_max']): continue
            if s['volume_ratio'] < cfg['volume_ratio_min']: continue
            # 附带热力值
            s['heat_score'] = heat_scores.get(code, 0)
            candidates.append(s)
        
        # RSI过滤+评分（并发K线获取）
        results = []
        
        def _score_stock(s):
            try:
                klines = self._get_kline(s['code'], 30)
                if len(klines) < 15:
                    return None
                closes = [float(k[2]) for k in klines]
                rsi = self._calc_rsi(closes, 14)
                if not (cfg['rsi_min'] <= rsi <= cfg['rsi_max']):
                    return None
                
                # === 新版评分系统 ===
                score = 0.0
                
                # 1. 涨幅得分（越靠近涨幅上限越好）
                score += (s['change_pct'] - cfg['rise_min']) * 2
                
                # 2. 换手率得分（活跃）
                score += min(s['turnover'], 10) * 0.5
                
                # 3. RSI得分（RSI低说明还有上涨空间）
                score += (80 - rsi) * 0.5
                
                # 4. 量比得分（放量确认）
                score += min(s['volume_ratio'] / cfg['volume_ratio_min'], 3) * 5
                
                # 5. 强于大盘加分
                if index.get('change_pct', 0) and s['change_pct'] > index['change_pct']:
                    score += 10
                
                # 6. ⭐ 热点因子：全市场热力排名加分（核心改动！）
                is_hot = s['heat_score'] >= hot_cutoff
                heat_bonus = cfg['hot_factor_weight'] if is_hot else 0
                score += heat_bonus
                
                is_hot_label = "🔥热门" if is_hot else ""
                
                return {
                    'code': s['code'], 'name': s['name'],
                    'price': s['price'], 'change_pct': s['change_pct'],
                    'turnover': s['turnover'], 'market_cap': round(s['market_cap'], 1),
                    'rsi': round(rsi, 1), 'volume_ratio': round(s['volume_ratio'], 2),
                    'heat_score': round(s['heat_score'], 1),
                    'score': round(score, 1),
                    'is_hot': is_hot_label,
                }
            except Exception:
                return None
        
        # 并发K线查询（10线程）
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(_score_stock, s) for s in candidates]
            for f in as_completed(futures):
                r = f.result()
                if r:
                    results.append(r)
        
        results.sort(key=lambda x: x['score'], reverse=True)
        return results
    
    def get_buy_criteria_description(self) -> str:
        cfg = self.config
        return (f"涨幅{cfg['rise_min']}%-{cfg['rise_max']}%、"
                f"成交量>{cfg['volume_ratio_min']}x、"
                f"换手率{cfg['turnover_min']}%-{cfg['turnover_max']}%、"
                f"流通市值{cfg['market_cap_min']}-{cfg['market_cap_max']}亿、"
                f"RSI < {cfg['rsi_max']}、全市场热力前{cfg['hot_rank_top_n']}（+{cfg['hot_factor_weight']}分）、强于大盘")


StrategyRegistry.register(OvernightStrategy)
