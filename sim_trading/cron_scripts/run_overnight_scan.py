#!/usr/bin/env python3
"""
一夜持股法 - 尾盘选股扫描 (14:50)
替代isolated cron的agentTurn模式
"""
import urllib.request
import urllib.error
import json
import sys

API_BASE = "http://localhost/api"

def api_get(path):
    url = f"{API_BASE}{path}"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return {"error": str(e)}

def main():
    # 扫描候选股
    print(f"[{__file__}] 开始一夜持股法尾盘选股扫描...", flush=True)
    result = api_get("/screen/overnight")
    
    if "error" in result:
        print(f"[ERROR] 扫描失败: {result['error']}", flush=True)
        return 1
    
    count = result.get("count", 0)
    index_info = result.get("index", {})
    
    print(f"大盘: {index_info.get('name', 'N/A')} {index_info.get('change_pct', 0):+.2f}% @ {index_info.get('price', 0)}", flush=True)
    print(f"候选股数量: {count}", flush=True)
    
    if count > 0:
        top5 = result.get("results", [])[:5]
        print(f"\nTop 5:", flush=True)
        for i, r in enumerate(top5, 1):
            heat_flag = "🔥热" if r.get("is_hot") == "🔥热门" else ""
            print(f"  {i}. {r['code']} {r['name']} +{r['change_pct']}% RSI={r['rsi']} "
                  f"评分={r['score']} 热力={r['heat_score']} {heat_flag}", flush=True)
    
    # 保存结果到临时文件供买入脚本读取
    with open("/tmp/overnight_scan_result.json", "w") as f:
        json.dump({"count": count, "results": result.get("results", [])[:10]}, f)
    
    print(f"\n扫描完成，保存 {count} 只候选到 /tmp/overnight_scan_result.json", flush=True)
    return 0

if __name__ == "__main__":
    sys.exit(main())
