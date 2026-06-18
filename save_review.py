#!/usr/bin/env python3
"""
保存复盘报告到数据库
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import database as db

def save_daily_review():
    """保存今日复盘报告"""
    # 读取复盘报告内容
    review_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'memory', '2026-06-17_复盘.md')
    
    if not os.path.exists(review_file):
        print(f"复盘报告文件不存在: {review_file}")
        return None
    
    with open(review_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 从报告中提取关键信息
    strategies = "一夜持股法, 价值投资"
    tags = "止损执行, 持仓调整, 策略优化"
    
    # 获取账户信息（从之前的记录中）
    total_profit = -14843.09  # 累计盈亏
    
    # 保存到数据库
    try:
        review_id = db.add_review(
            date="2026-06-17",
            content=content,
            strategies=strategies,
            profit=total_profit,
            tags=tags
        )
        print(f"复盘报告保存成功，ID: {review_id}")
        return review_id
    except Exception as e:
        print(f"保存复盘报告失败: {e}")
        return None

if __name__ == "__main__":
    save_daily_review()