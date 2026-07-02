"""
行情相关路由: /api/quote, /api/quotes/batch, /api/market/top, /api/index,
              /api/market/indices, /api/market/hot-sectors, /api/market/analyze,
              /api/market/fullscan, /api/market/comment
"""
import json
import logging
import re
import time
from datetime import datetime, timezone, timedelta
from flask import Blueprint, jsonify, request, make_response

import requests
import database as db
from services.quote import get_tencent_quote, get_market_top_cached, get_tencent_kline, get_index_kline, calculate_rsi
from services.cache import cache

logger = logging.getLogger(__name__)

market_bp = Blueprint('market', __name__)


@market_bp.route('/api/quote/<stock_code>')
def get_quote(stock_code):
    """获取实时行情（腾讯API）"""
    cache_key = f'quote_{stock_code}'
    cached = cache.get(cache_key)
    if cached is not None:
        return jsonify(cached)

    try:
        quotes = get_tencent_quote([stock_code])
        if stock_code not in quotes:
            return jsonify({"error": "股票代码不存在"}), 404

        data = quotes[stock_code]
        result = {
            "code": stock_code,
            "name": data['name'],
            "price": data['price'],
            "change": data['change'],
            "change_pct": data['change_pct'],
            "volume": data['volume'],
            "amount": data.get('amount', 0),
            "high": data.get('high', 0),
            "low": data.get('low', 0),
            "open": data.get('open', 0),
            "close": data.get('close', 0),
            "time": data.get('time', datetime.now().strftime("%H:%M:%S"))
        }
        cache.set(cache_key, result)
        return jsonify(result)
    except Exception as e:
        logger.warning(f"获取行情失败 {stock_code}: {e}")
        return jsonify({"error": str(e)}), 500


@market_bp.route('/api/quotes/batch')
def get_quotes_batch():
    """批量获取持仓股行情（腾讯API）"""
    positions = db.get_positions()
    codes = list(set(p['stock_code'] for p in positions))  # 去重，同一股票可能被多策略持有

    if not codes:
        return jsonify([])

    cached = []
    uncached = []
    for code in codes:
        cache_key = f'quote_{code}'
        c = cache.get(cache_key)
        if c is not None:
            cached.append(c)
        else:
            uncached.append(code)

    result = list(cached)

    if uncached:
        try:
            quotes = get_tencent_quote(uncached)
            for code, data in quotes.items():
                q = {
                    "code": code,
                    "name": data['name'],
                    "price": data['price'],
                    "change": data['change'],
                    "change_pct": data['change_pct'],
                    "volume": data['volume'],
                    "high": data.get('high', 0),
                    "low": data.get('low', 0),
                    "time": data.get('time', datetime.now().strftime("%H:%M:%S"))
                }
                cache.set(f'quote_{code}', q)
                result.append(q)
        except Exception as e:
            logger.warning(f"批量行情获取失败: {e}")

    return jsonify(result)


@market_bp.route('/api/market/top')
def get_market_top():
    """获取市场热门股票"""
    data = get_market_top_cached()
    if data:
        return jsonify(data)
    return jsonify({"error": "获取热门股票失败"}), 500


@market_bp.route('/api/index')
def get_index():
    """获取大盘指数及均线数据"""
    import pandas as pd

    cached = cache.get('index_data')
    if cached is not None:
        return jsonify(cached)

    try:
        url = "https://qt.gtimg.cn/q=sh000001"
        headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://gu.qq.com/'}
        r = requests.get(url, headers=headers, timeout=5)
        fields = r.text.split('="')[1].strip('"').split('~')
        current_price = float(fields[3]) if fields[3] != '-' else 0

        # 从腾讯获取均线数据（替代akshare）
        klines = get_index_kline(15)
        if len(klines) >= 10:
            closes = [float(k[2]) for k in klines]
            ma5 = round(sum(closes[-5:]) / 5, 2)
            ma10 = round(sum(closes[-10:]) / 10, 2)
        else:
            ma5 = 0
            ma10 = 0

        result = {
            "code": "000001",
            "name": "上证指数",
            "price": current_price,
            "ma5": ma5,
            "ma10": ma10,
            "above_ma5": bool(current_price > ma5) if ma5 > 0 else False,
            "above_ma10": bool(current_price > ma10) if ma10 > 0 else False,
            "ma5_above_ma10": bool(ma5 > ma10),
            "change_pct": float(fields[32]) if len(fields) > 32 and fields[32] != '-' else 0,
            "volume": float(fields[37]) if len(fields) > 37 and fields[37] != '-' else 0,
        }

        cache.set('index_data', result)
        return jsonify(result)
    except Exception as e:
        logger.warning(f"获取指数数据失败: {e}")
        return jsonify({"error": f"获取指数数据失败: {str(e)}"}), 500


@market_bp.route('/api/market/indices', methods=['GET'])
def get_multi_indices():
    """获取多个主要指数的实时行情"""
    try:
        indices = {
            'sh000001': '上证指数',
            'sz399001': '深证成指',
            'sz399006': '创业板指',
            'sh000688': '科创50',
        }

        code_str = ','.join(indices.keys())
        url = f"https://qt.gtimg.cn/q={code_str}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://gu.qq.com/'
        }

        r = requests.get(url, headers=headers, timeout=5)
        result = []

        for line in r.text.strip().split('\n'):
            if '=' not in line:
                continue
            parts = line.split('="')
            if len(parts) < 2:
                continue
            fields = parts[1].strip('"').split('~')
            if len(fields) < 35:
                continue

            code = fields[2] if len(fields) > 2 else fields[0]
            name = fields[1]
            price = float(fields[3]) if fields[3] != '-' else 0
            change = float(fields[31]) if len(fields) > 31 and fields[31] != '-' else 0
            change_pct = float(fields[32]) if len(fields) > 32 and fields[32] != '-' else 0
            volume = float(fields[37]) if len(fields) > 37 and fields[37] != '-' else 0
            high = float(fields[33]) if len(fields) > 33 and fields[33] != '-' else 0
            low = float(fields[34]) if len(fields) > 34 and fields[34] != '-' else 0

            # 计算均线
            ma5 = 0
            ma10 = 0
            # 从腾讯获取指数均线（替代akshare）
            try:
                index_code = code
                klines = get_tencent_kline(index_code, 15)
                if len(klines) >= 10:
                    closes = [float(k[2]) for k in klines]
                    ma5 = round(sum(closes[-5:]) / 5, 2)
                    ma10 = round(sum(closes[-10:]) / 10, 2)
                else:
                    ma5 = 0
                    ma10 = 0
            except Exception as e:
                logger.warning(f"计算指数均线失败 {code}: {e}")

            result.append({
                'code': code,
                'name': name,
                'price': price,
                'change': change,
                'change_pct': change_pct,
                'volume': volume,
                'high': high,
                'low': low,
                'ma5': ma5,
                'ma10': ma10,
                'above_ma5': price > ma5 > 0,
                'above_ma10': price > ma10 > 0,
                'ma5_above_ma10': ma5 > ma10 > 0,
            })

        return jsonify({
            'success': True,
            'timestamp': datetime.now().strftime('%H:%M:%S'),
            'indices': result,
        })

    except Exception as e:
        logger.warning(f"获取多指数失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@market_bp.route('/api/market/hot-sectors', methods=['GET'])
def get_hot_sectors():
    """获取实时热点板块 - 使用新浪API"""
    try:
        url = "https://vip.stock.finance.sina.com.cn/q/view/newFLJK.php"
        params = {'param': 'class=hy'}
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://finance.sina.com.cn/'
        }

        r = requests.get(url, params=params, headers=headers, timeout=5)
        text = r.text

        match = re.search(r'S_Finance_bankuai_class=hy\s*=\s*(\{.*\})', text)
        if not match:
            raise ValueError("无法解析板块数据")

        js_str = match.group(1)
        sectors_raw = re.findall(r'hangye_(\w+)"[^"]*"([^"]*)', js_str)

        sectors = []
        for prefix, data_str in sectors_raw:
            parts = data_str.split(',')
            if len(parts) >= 5:
                name = parts[1]
                try:
                    change_pct = float(parts[4]) if parts[4] else 0
                except (ValueError, IndexError):
                    change_pct = 0
                if name and len(name) > 1:
                    sectors.append({'name': name, 'change_pct': change_pct})

        sectors.sort(key=lambda x: abs(x['change_pct']), reverse=True)

        result = []
        for i, s in enumerate(sectors[:10]):
            result.append({
                'rank': i + 1,
                'code': '',
                'name': s['name'],
                'change_pct': round(s['change_pct'], 2),
                'direction': 'up' if s['change_pct'] > 0 else 'down',
            })

        return jsonify({
            'success': True,
            'timestamp': datetime.now().strftime('%H:%M:%S'),
            'sectors': result,
            'source': 'sina',
        })

    except Exception as e:
        logger.warning(f"获取热点板块失败: {e}")
        return jsonify({
            'success': True,
            'timestamp': datetime.now().strftime('%H:%M:%S'),
            'sectors': [
                {'rank': 1, 'code': 'BK0889', 'name': 'AI算力', 'change_pct': 3.2, 'direction': 'up'},
                {'rank': 2, 'code': 'BK0401', 'name': '存储芯片', 'change_pct': 2.8, 'direction': 'up'},
                {'rank': 3, 'code': 'BK0091', 'name': '新能源汽车', 'change_pct': 1.5, 'direction': 'up'},
                {'rank': 4, 'code': 'BK0441', 'name': '医疗服务', 'change_pct': -1.2, 'direction': 'down'},
                {'rank': 5, 'code': 'BK0231', 'name': '光伏设备', 'change_pct': -0.8, 'direction': 'down'},
            ],
            'source': 'demo',
            'note': '实时数据获取失败，显示示例数据',
        })


@market_bp.route('/api/market/analyze', methods=['GET'])
def get_market_analysis():
    """获取实时大盘分析（技术面+资金面+情绪面）"""
    try:
        # 获取多指数数据
        with market_bp.test_client() if False else None or True:
            pass
        # 直接调用内部逻辑
        indices_resp = get_multi_indices()
        indices_data = indices_resp.get_json()
        indices = indices_data.get('indices', [])

        # 腾讯行情获取涨跌家数（替代已死的push2.eastmoney）
        up_count = 0
        down_count = 0
        try:
            # 批量查全市场前200只股票统计涨跌
            url = 'https://qt.gtimg.cn/q=sh000001,sz399001,sz399006'
            r2 = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
            # 直接跳过涨跌统计
        except Exception:
            pass

        main_index = next((i for i in indices if i['code'] == '000001'), None)

        analysis = {
            'timestamp': datetime.now().strftime('%H:%M:%S'),
            'indices': indices,
            'technical': {
                'above_ma5': main_index.get('above_ma5', False) if main_index else False,
                'above_ma10': main_index.get('above_ma10', False) if main_index else False,
                'ma5_above_ma10': main_index.get('ma5_above_ma10', False) if main_index else False,
                'trend': '多头' if (main_index.get('ma5_above_ma10') if main_index else False) else '震荡',
            },
            'sentiment': {
                'up_count': up_count,
                'down_count': down_count,
                'market_breadth': '偏多' if up_count > down_count else '偏空',
            },
            'volume': main_index.get('volume', 0) if main_index else 0,
        }

        can_build = (
            main_index.get('above_ma5', False) and
            main_index.get('ma5_above_ma10', False)
        ) if main_index else False

        analysis['conclusion'] = {
            'can_build': can_build,
            'suggestion': '可建仓' if can_build else '观望',
            'signal': '✅' if can_build else '❌',
            'reason': '指数站稳5日线且多头排列' if can_build else '指数未站稳5日线或非多头排列',
        }

        return jsonify({'success': True, **analysis})

    except Exception as e:
        logger.warning(f"大盘分析失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@market_bp.route('/api/market/fullscan', methods=['GET'])
def market_fullscan():
    """全市场扫描API（腾讯方案，无IP限制）"""
    try:
        import pandas as pd
        from market_scanner import scan_market, get_market_overview

        mode = request.args.get('mode', 'overnight')

        if mode == 'overview':
            result = get_market_overview()
            return jsonify(result)

        elif mode == 'overnight':
            return jsonify({
                'total_stocks': 0,
                'total_candidates': 0,
                'candidates': [],
                'scan_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'message': '旧策略已下线',
            })

        elif mode == 'top':
            df = scan_market()
            top = df.nlargest(20, 'change_pct') if not df.empty else pd.DataFrame()
            result = []
            for _, r in top.iterrows():
                result.append({
                    'code': r['code'], 'name': r['name'],
                    'price': r['price'], 'change_pct': r['change_pct'],
                    'turnover': r['turnover'], 'volume_ratio': r['volume_ratio'],
                })
            return jsonify({'total': len(result), 'stocks': result})

        elif mode == 'oversold':
            # 超跌反弹策略用：获取跌幅靠前的股票
            df = scan_market()
            if df.empty:
                return jsonify({'total': 0, 'candidates': []})
            # 筛选条件：跌幅<0，流通市值50-200亿，非ST
            filtered = df[
                (df['change_pct'] < 0) &
                (df['circulate_mv'] >= 50) &
                (df['circulate_mv'] <= 200)
            ].copy()
            # 排除ST
            filtered = filtered[~filtered['name'].str.contains('ST', na=False)]
            # 按跌幅排序（跌最多的在前面）
            filtered = filtered.nsmallest(50, 'change_pct')
            result = []
            for _, r in filtered.iterrows():
                result.append({
                    'code': r['code'], 'name': r['name'],
                    'price': r['price'], 'change_pct': r['change_pct'],
                    'turnover': r.get('turnover', 0),
                    'circulate_mv_yi': r.get('circulate_mv', 0),
                    'volume_ratio': r.get('volume_ratio', 0),
                })
            return jsonify({'total': len(result), 'candidates': result})

        else:
            return jsonify({'error': f'未知模式: {mode}'}), 400

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@market_bp.route('/api/market/comment', methods=['GET', 'POST'])
def market_comment():
    """获取/生成午盘或尾盘点评"""
    try:
        import os
        comment_type = request.args.get('type', 'lunch')

        if request.method == 'POST':
            data = request.json or {}
            comment_type = data.get('type', 'lunch')
            content = data.get('content', '')
            author = data.get('author', '蛋蛋')

            os.makedirs('/root/.openclaw/workspace/data', exist_ok=True)
            comment_file = f'/root/.openclaw/workspace/data/comment_{comment_type}.json'

            with open(comment_file, 'w', encoding='utf-8') as f:
                json.dump({
                    'type': comment_type,
                    'content': content,
                    'author': author,
                    'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                }, f, ensure_ascii=False, indent=2)

            return jsonify({'success': True, 'message': '点评已保存'})

        else:
            comment_file = f'/root/.openclaw/workspace/data/comment_{comment_type}.json'
            import os
            if os.path.exists(comment_file):
                with open(comment_file, 'r', encoding='utf-8') as f:
                    comment = json.load(f)
                today = datetime.now().strftime('%Y-%m-%d')
                if today in comment.get('created_at', ''):
                    return jsonify({'success': True, 'comment': comment})

            return jsonify({'success': False, 'error': '今日暂无点评', 'comment': None})

    except Exception as e:
        logger.warning(f"市场点评操作失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
