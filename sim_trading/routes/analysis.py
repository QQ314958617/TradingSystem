"""
分析相关路由: /api/analyze, /api/search, /api/indicators, /api/screen/overnight
"""
import logging
import re
import traceback
from datetime import datetime
from flask import Blueprint, jsonify, request

import database as db

logger = logging.getLogger(__name__)

analysis_bp = Blueprint('analysis', __name__)

# 腾讯K线替代akshare
from services.quote import get_tencent_kline, calculate_rsi


@analysis_bp.route('/api/analyze/<stock_code>')
def analyze_stock(stock_code):
    """价值投资分析报告v2.0（整合价值评估师框架）"""
    import value_analyzer as va
    try:
        if not stock_code.isdigit():
            match = re.search(r'\(?(\d{6})\)?', stock_code)
            if match:
                stock_code = match.group(1)
            else:
                code = va.get_code_by_name(stock_code)
                if not code:
                    return jsonify({'error': f'未找到股票：{stock_code}'}), 404
                stock_code = code
        report = va.analyze_stock(stock_code)
        return jsonify(report)
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@analysis_bp.route('/api/search')
def search_stocks():
    """股票搜索（名称或代码模糊匹配）"""
    import value_analyzer as va
    keyword = request.args.get('q', '').strip()
    if not keyword or len(keyword) < 1:
        return jsonify([])
    results = va.search_stocks(keyword)
    return jsonify(results)


@analysis_bp.route('/api/indicators/<stock_code>')
def get_indicators(stock_code):
    """获取股票技术指标 RSI / MACD / KDJ / 布林带"""
    try:
        import pandas as pd
        import numpy as np
        from openclaw.indicators import (
            calculate_rsi, calculate_macd, calculate_kdj,
            calculate_bollinger, calculate_volume_ratio, get_signal
        )

        try:
            klines = get_tencent_kline(stock_code, 60)
            if len(klines) < 20:
                return jsonify({"error": "数据不足"}), 400

            # 腾讯K线格式: [日期, 开盘, 收盘, 最高, 最低, 成交量, ...]
            close = [float(k[2]) for k in klines]
            high = [float(k[3]) for k in klines]
            low = [float(k[4]) for k in klines]
            volume = [float(k[5]) for k in klines]
        except Exception as e:
            return jsonify({"error": f"获取数据失败: {str(e)}"}), 500

        result = {
            "code": stock_code,
            "close": close[-1],
            "high": high[-1],
            "low": low[-1],
            "volume": volume[-1],
            "date": klines[-1][0],
        }

        rsi = calculate_rsi(close)
        if rsi:
            result["rsi"] = rsi

        macd = calculate_macd(close)
        if macd:
            result["macd"] = macd

        kdj = calculate_kdj(high, low, close)
        if kdj:
            result["kdj"] = kdj

        bollinger = calculate_bollinger(close)
        if bollinger:
            result["bollinger"] = bollinger

        vol_ratio = calculate_volume_ratio(volume)
        if vol_ratio:
            result["volume_ratio"] = vol_ratio

        result["signal"] = get_signal(
            result.get("rsi"),
            result.get("macd"),
            result.get("kdj")
        )

        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500


@analysis_bp.route('/api/screen/overnight', methods=['GET'])
def screen_overnight_route():
    """旧策略已下线"""
    return jsonify({
        "success": False,
        "error": "一夜持股法策略已下线，请使用新策略",
        "results": []
    }), 410
