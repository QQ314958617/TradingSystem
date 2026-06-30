#!/usr/bin/env python3
"""
价值投资每周扫描 (周一09:30)
默认无参数，通过API扫描
"""
import urllib.request
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
    print(f"[{__file__}] 价值投资每周扫描...", flush=True)
    
    # 查当前策略2持仓
    portfolio = api_get("/portfolio?strategy_id=2")
    if "error" in portfolio:
        print(f"[ERROR] {portfolio['error']}", flush=True)
        return 1
    
    positions = portfolio.get("positions", {}) or {}
    print(f"当前价值持仓: {len(positions)} 只", flush=True)
    for code, p in positions.items():
        print(f"  {code} {p.get('stock_name','')} {p.get('shares',0)}股 @{p.get('avg_cost',0)}", flush=True)
    
    # 运行价值扫描器
    try:
        sys.path.insert(0, "/root/.openclaw/workspace/sim_trading")
        import subprocess
        # 运行扫描器，capture输出
        result = subprocess.run(
            ["python3", "/root/.openclaw/workspace/sim_trading/value_screener.py"],
            capture_output=True, text=True, timeout=60
        )
        print(f"扫描器输出:", flush=True)
        for line in result.stdout.split("\n")[:30]:
            if line.strip():
                print(f"  {line}", flush=True)
        if result.stderr:
            print(f"  [stderr] {result.stderr[:500]}", flush=True)
    except FileNotFoundError:
        print("[WARN] value_screener.py 不存在", flush=True)
    except Exception as e:
        print(f"[WARN] 扫描器执行失败（非致命）: {e}", flush=True)
    
    print("\n价值投资每周扫描完成", flush=True)
    return 0

if __name__ == "__main__":
    sys.exit(main())
