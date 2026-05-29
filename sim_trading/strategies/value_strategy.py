"""
价值投资策略 v3.0 — 分批建仓+仓位管理版
================================
核心框架：多因子价值评分体系（满分85）
因子权重：估值30 + 盈利质量20 + 成长性20 + 财务健康15

v3.0 升级:
- 分批建仓：首次50% → 加仓25% → 满仓25%
- 分批减仓：涨+15%卖半 → 涨+25%清仓
- 加仓条件：回调-5%且基本面不变
- PEG估值判断（PE/Growth < 1.5，避免估值陷阱）
- ROE连续4年 > 10%稳定性检查
- 营收/利润双增长（排除衰退型低PE股）
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies import BaseStrategy, StrategyRegistry
from datetime import time as t_time
import json
import requests

import buffett_analyzer as ba


class ValueInvestingStrategy(BaseStrategy):
    """价值投资策略 v3.0 — 分批建仓+仓位管理"""
    
    name = "价值投资"
    strategy_type = "value"
    description = "多因子价值评分+分批建仓/加仓/减仓，中线持有"
    
    def __init__(self, strategy_id: int, config: dict = None):
        super().__init__(strategy_id, config)
        self.config = {
            # 买入门槛（必须全部满足）
            'pe_max': 20,                  # PE上限
            'peg_max': 1.5,                # PEG上限
            'roe_min': 12.0,               # ROE下限%
            'roe_years': 4,                # ROE连续达标年数
            'revenue_growth_min': 0,       # 营收增长最低（排除衰退）
            'profit_growth_min': 0,        # 利润增长最低
            'debt_ratio_max': 65.0,        # 负债率上限%
            
            # === 仓位管理（v3.0新增）===
            'initial_position_pct': 50,    # 首次建仓：50%目标仓位
            'add_position_pct': 25,        # 每次加仓：25%目标仓位
            'add_trigger_drop': -5.0,      # 加仓触发：回调-5%
            'max_position_phases': 3,      # 最多加仓次数（含首次）
            'reduce_trigger_gain': 15.0,   # 减仓触发：涨+15%卖一半
            'clear_trigger_gain': 25.0,    # 清仓触发：涨+25%全卖
            
            # 卖出规则
            'stop_loss': -7.0,             # 中线止损（2026-05-29收紧：-8%→-7%）
            'target_pe': 28,               # 目标PE止盈
            'max_hold_days': 90,           # 最长持有天数
            'recheck_interval_days': 14,   # 每两周重新评估
            
            # 评分权重
            'weight_pe': 30,
            'weight_roe': 20,
            'weight_growth': 20,
            'weight_financial': 15,
            'weight_moat': 15,
            **(config or {})
        }
    
    def is_trading_time(self) -> bool:
        bj = self.get_bj_time()
        now = bj.time()
        return t_time(9, 30) <= now <= t_time(15, 0)
    
    # ─── 仓位管理（v3.0核心）───
    
    def calc_position_size(self, per_stock_capital: float, phase: int = 1) -> float:
        """计算当前阶段应买入的金额
        
        Args:
            per_stock_capital: 单只股票的总目标资金（如¥100,000）
            phase: 当前阶段 1=首次建仓, 2=第一次加仓, 3=第二次加仓
        
        Returns:
            本次应买入的金额
        """
        cfg = self.config
        if phase == 1:
            return per_stock_capital * cfg['initial_position_pct'] / 100
        elif phase <= cfg['max_position_phases']:
            return per_stock_capital * cfg['add_position_pct'] / 100
        return 0  # 已满仓
    
    def should_add_position(self, code: str, avg_cost: float, current_price: float,
                            current_phase: int) -> dict:
        """判断是否应该加仓
        
        Returns:
            {'add': True/False, 'reason': str, 'next_phase': int}
        """
        cfg = self.config
        
        # 已满仓
        if current_phase >= cfg['max_position_phases']:
            return {'add': False, 'reason': '已满仓，不再加仓'}
        
        # 计算回调幅度
        drop_pct = (current_price - avg_cost) / avg_cost * 100
        
        # 回调未达标
        if drop_pct > cfg['add_trigger_drop']:
            return {'add': False, 'reason': f'回调{drop_pct:.1f}%，未达{cfg["add_trigger_drop"]}%加仓线'}
        
        # 基本面检查（加仓前必须确认基本面没恶化）
        eval_result = self.evaluate_stock(code)
        if eval_result.get('score', 0) < 40:
            return {'add': False, 'reason': f'基本面恶化（评分{eval_result.get("score", 0)}），不加仓'}
        
        return {
            'add': True,
            'reason': f'回调{drop_pct:.1f}%触发加仓，基本面评分{eval_result["score"]}分正常',
            'next_phase': current_phase + 1
        }
    
    def should_reduce_position(self, code: str, avg_cost: float, current_price: float,
                               current_shares: int) -> dict:
        """判断是否应该减仓
        
        Returns:
            {'reduce': True/False, 'action': 'reduce'/'clear'/'hold', 'sell_shares': int, 'reason': str}
        """
        cfg = self.config
        gain_pct = (current_price - avg_cost) / avg_cost * 100
        
        # 涨+25%清仓
        if gain_pct >= cfg['clear_trigger_gain']:
            return {
                'reduce': True,
                'action': 'clear',
                'sell_shares': current_shares,
                'reason': f'涨幅{gain_pct:.1f}% ≥ {cfg["clear_trigger_gain"]}%，触发清仓'
            }
        
        # 涨+15%减半
        if gain_pct >= cfg['reduce_trigger_gain']:
            sell_shares = (current_shares // 200) * 100  # 卖一半，取整百
            if sell_shares < 100:
                sell_shares = current_shares  # 不足200股就全卖
            return {
                'reduce': True,
                'action': 'reduce',
                'sell_shares': sell_shares,
                'reason': f'涨幅{gain_pct:.1f}% ≥ {cfg["reduce_trigger_gain"]}%，减仓一半'
            }
        
        return {'reduce': False, 'action': 'hold', 'sell_shares': 0, 'reason': ''}
    
    # ─── 腾讯额外数据 ───
    
    def _get_tencent_extended(self, code: str) -> dict:
        """从腾讯获取PE/股息率/PB/市值"""
        try:
            prefix = "sh" if code.startswith(('6', '5')) else "sz"
            r = requests.get(
                f"https://qt.gtimg.cn/q={prefix}{code}",
                headers={'User-Agent': 'Mozilla/5.0'},
                timeout=5
            )
            fields = r.text.split('="')[1].strip('"').split('~')
            if len(fields) < 45:
                return {}
            return {
                'pe': float(fields[39]) if fields[39] and fields[39] != '-' else None,
                'dividend_yield': float(fields[42]) if len(fields) > 42 and fields[42] and fields[42] != '-' else None,
                'total_mv': float(fields[45]) if len(fields) > 45 and fields[45] and fields[45] != '-' else None,
                'circulate_mv': float(fields[44]) if len(fields) > 44 and fields[44] and fields[44] != '-' else None,
            }
        except Exception:
            return {}
    
    # ─── 评分体系 ───
    
    def _score_pe(self, pe_val: float) -> tuple:
        """PE估值评分（满分30）"""
        if pe_val <= 8:
            return 30, f"PE={pe_val:.1f} ⭐ 极度低估"
        elif pe_val <= 10:
            return 27, f"PE={pe_val:.1f} ✅ 明显低估"
        elif pe_val <= 13:
            return 23, f"PE={pe_val:.1f} ✅ 合理偏低"
        elif pe_val <= 16:
            return 18, f"PE={pe_val:.1f} ✅ 合理估值"
        elif pe_val <= 20:
            return 12, f"PE={pe_val:.1f} ⚠️ 接近上限"
        else:
            return 0, f"PE={pe_val:.1f} ❌ 超过{self.config['pe_max']}倍"
    
    def _score_roe(self, roe_val: float, roe_history: list) -> tuple:
        """ROE评分（满分20），检测稳定性"""
        cfg = self.config
        current = roe_val
        
        if current >= 20:
            base = 12
            desc = f"当前ROE={current:.1f}% ⭐ 优秀"
        elif current >= 15:
            base = 10
            desc = f"当前ROE={current:.1f}% ✅ 良好"
        elif current >= cfg['roe_min']:
            base = 6
            desc = f"当前ROE={current:.1f}% ⚠️ 及格线"
        else:
            return 0, f"当前ROE={current:.1f}% ❌ 低于{cfg['roe_min']}%"
        
        stable_count = sum(1 for r in roe_history if r is not None and r >= 10)
        if stable_count >= cfg['roe_years']:
            base += 8
            desc += f"，连续{stable_count}年>10% ✅"
        elif stable_count >= 3:
            base += 5
            desc += f"，{stable_count}/4年>10%"
        else:
            desc += "，ROE波动大 ⚠️"
        
        return min(base, 20), desc
    
    def _score_growth(self, rev_growth, prof_growth) -> tuple:
        """成长性评分（满分20）"""
        cfg = self.config
        
        if rev_growth is None and prof_growth is None:
            return 5, "成长数据无法获取，保守给分"
        
        rev = rev_growth if rev_growth else 0
        prof = prof_growth if prof_growth else 0
        avg_growth = (rev + prof) / 2
        
        if (rev_growth is not None and rev_growth < cfg['revenue_growth_min']) or \
           (prof_growth is not None and prof_growth < cfg['profit_growth_min']):
            return 0, f"营收{rev_growth:.1f}%/利润{prof_growth:.1f}% ❌ 衰退，排除"
        
        if avg_growth >= 25:
            score = 20
            desc = f"高增长✅ 营收+{rev:.1f}%/利润+{prof:.1f}%"
        elif avg_growth >= 15:
            score = 16
            desc = f"稳健增长✅ 营收+{rev:.1f}%/利润+{prof:.1f}%"
        elif avg_growth >= 5:
            score = 12
            desc = f"温和增长⚠️ 营收+{rev:.1f}%/利润+{prof:.1f}%"
        elif avg_growth >= 0:
            score = 6
            desc = f"增速放缓⚠️ 营收+{rev:.1f}%/利润+{prof:.1f}%"
        else:
            score = 0
            desc = f"衰退❌ 营收{rev:.1f}%/利润{prof:.1f}%"
        
        return score, desc
    
    def _score_financial_health(self, debt_ratio: float, gross_margin: float) -> tuple:
        """财务健康评分（满分15）"""
        score = 0
        items = []
        
        if debt_ratio is not None:
            if debt_ratio <= 30:
                score += 8; items.append(f"负债率{debt_ratio:.1f}% ⭐ 低杠杆")
            elif debt_ratio <= 50:
                score += 6; items.append(f"负债率{debt_ratio:.1f}% ✅ 正常")
            elif debt_ratio <= 65:
                score += 3; items.append(f"负债率{debt_ratio:.1f}% ⚠️ 偏高")
            else:
                items.append(f"负债率{debt_ratio:.1f}% ❌ 过高")
        
        if gross_margin is not None:
            if gross_margin >= 60:
                score += 7; items.append(f"毛利率{gross_margin:.1f}% ⭐ 强护城河")
            elif gross_margin >= 40:
                score += 5; items.append(f"毛利率{gross_margin:.1f}% ✅ 较好")
            elif gross_margin >= 20:
                score += 3; items.append(f"毛利率{gross_margin:.1f}% ⚠️ 一般")
            else:
                items.append(f"毛利率{gross_margin:.1f}% ⚠️ 低毛利")
        
        return score, "；".join(items) if items else "财务数据不足"
    
    # ─── 评分入口 ───
    
    def evaluate_stock(self, code: str) -> dict:
        """完整价值评估流程"""
        report = ba.build_report(code)
        if 'error' in report:
            return {'pass': False, 'error': report['error']}
        
        ext = self._get_tencent_extended(code)
        
        indicators = report.get('indicators', {})
        pe_val = indicators.get('PE', {}).get('value', 999)
        roe_val = 0
        roe_history = []
        for k, v in indicators.items():
            if 'ROE' in k:
                roe_val = v.get('value', 0)
                roe_history = v.get('history', [])
                break
        
        fin = ba.get_financial_data(code)
        rev_growth = fin.get('revenue_growth')
        prof_growth = fin.get('profit_growth')
        debt_ratio = None
        gross_margin = None
        for k, v in indicators.items():
            if '负债' in k or '资产负债' in k:
                debt_ratio = v.get('value')
            if '毛利' in k:
                gross_margin = v.get('value')
        
        # PEG计算
        growth_avg = 0
        if rev_growth is not None and prof_growth is not None:
            growth_avg = (rev_growth + prof_growth) / 2
        elif rev_growth is not None:
            growth_avg = rev_growth
        
        peg = pe_val / growth_avg if growth_avg > 0 else 999
        peg_pass = True if pe_val <= 10 else (peg <= self.config['peg_max'] if growth_avg > 0 else False)
        
        # 各维度评分
        pe_score, pe_desc = self._score_pe(pe_val)
        roe_score, roe_desc = self._score_roe(roe_val, roe_history)
        growth_score, growth_desc = self._score_growth(rev_growth, prof_growth)
        fin_score, fin_desc = self._score_financial_health(debt_ratio, gross_margin)
        
        total_score = pe_score + roe_score + growth_score + fin_score
        
        # 买入判断
        failures = []
        if pe_val > self.config['pe_max']:
            failures.append(f"PE={pe_val:.1f} > {self.config['pe_max']}")
        if peg_pass is False:
            failures.append(f"PEG={peg:.2f} > {self.config['peg_max']}（成长不足以支撑估值）")
        if roe_val < self.config['roe_min'] and roe_val > 0:
            failures.append(f"ROE={roe_val:.1f}% < {self.config['roe_min']}%")
        if roe_val <= 0:
            failures.append(f"ROE={roe_val:.1f}% ≤ 0，不符合价值投资标准")
        if rev_growth is not None and rev_growth < self.config['revenue_growth_min']:
            failures.append(f"营收增长{rev_growth:.1f}%，负增长")
        if prof_growth is not None and prof_growth < 0:
            failures.append(f"净利润增长{prof_growth:.1f}%，负增长（价值陷阱风险）")
        if debt_ratio is not None and debt_ratio > self.config['debt_ratio_max']:
            failures.append(f"负债率{debt_ratio:.1f}% > {self.config['debt_ratio_max']}%")
        
        current_price = report.get('current_price', 0)
        target_price = report.get('target_price', 0)
        if target_price and current_price:
            safety_margin = (target_price - current_price) / current_price * 100
            if safety_margin <= 0:
                failures.append(f"现价¥{current_price} ≥ 目标价¥{target_price}，无安全边际")
        
        buy_signal = len(failures) == 0 and total_score >= 50
        
        return {
            'pass': buy_signal,
            'score': total_score,
            'max_score': 85,
            'score_breakdown': {
                'pe': {'score': pe_score, 'max': 30, 'desc': pe_desc},
                'roe': {'score': roe_score, 'max': 20, 'desc': roe_desc},
                'growth': {'score': growth_score, 'max': 20, 'desc': growth_desc},
                'financial': {'score': fin_score, 'max': 15, 'desc': fin_desc},
            },
            'metrics': {
                'pe': pe_val, 'peg': peg, 'roe': roe_val,
                'rev_growth': rev_growth, 'prof_growth': prof_growth,
                'debt_ratio': debt_ratio, 'gross_margin': gross_margin,
                'dividend_yield': ext.get('dividend_yield'),
                'current_price': current_price,
                'target_price': target_price,
            },
            'failures': failures,
            'report': report,
            'action': '买入' if buy_signal else '不符合条件：' + '；'.join(failures[:3]),
        }
    
    # ─── 退出决策（v3.0 分批减仓）───
    
    def should_sell(self, code: str, cost_price: float, current_price: float,
                    highest_since_buy: float, hold_days: int,
                    current_shares: int = 0) -> tuple:
        """多维度卖出判断（v3.0支持分批减仓）
        
        Returns:
            (should_sell: bool, reason: str, sell_shares: int or None)
            sell_shares=None表示全卖，具体数字表示部分卖出
        """
        cfg = self.config
        loss_pct = (current_price - cost_price) / cost_price * 100
        
        # 止损（无条件，全卖）
        if loss_pct <= cfg['stop_loss']:
            return True, f"止损触发：亏损{loss_pct:.1f}%（≤{cfg['stop_loss']}%）", None
        
        # 超时卖出（全卖）
        if hold_days >= cfg['max_hold_days']:
            return True, f"超时卖出：已持有{hold_days}天（上限{cfg['max_hold_days']}天）", None
        
        # 分批减仓逻辑
        if current_shares > 0:
            reduce_result = self.should_reduce_position(code, cost_price, current_price, current_shares)
            if reduce_result['reduce']:
                return True, reduce_result['reason'], reduce_result['sell_shares']
        
        # 重新估值检查（每两周）
        if hold_days > 0 and hold_days % cfg['recheck_interval_days'] == 0:
            eval_result = self.evaluate_stock(code)
            if eval_result.get('score', 0) < 30:
                return True, f"基本面恶化：评分{eval_result['score']}分，建议退出", None
        
        # 目标PE止盈（全卖）
        report = ba.build_report(code)
        if 'error' not in report:
            pe_val = report.get('indicators', {}).get('PE', {}).get('value', 999)
            if pe_val >= cfg['target_pe']:
                return True, f"目标PE到达：PE={pe_val:.1f} ≥ {cfg['target_pe']}", None
        
        return False, "", 0


# 注册策略
StrategyRegistry.register(ValueInvestingStrategy)
