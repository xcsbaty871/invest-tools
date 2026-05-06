"""
猪肉股数据爬虫
数据源: 东方财富 (eastmoney)
追踪: 牧原股份、温氏股份、新希望、正邦科技、天邦食品等
运行方式: python scrape_pork.py
"""

import json
import time
import random
import requests
from datetime import datetime

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
    'Referer': 'https://www.eastmoney.com/',
}

# 猪肉产业链主要个股
STOCKS = [
    {'code': '002714', 'name': '牧原股份', 'market': 'SZ'},
    {'code': '300498', 'name': '温氏股份', 'market': 'SZ'},
    {'code': '000876', 'name': '新希望',   'market': 'SZ'},
    {'code': '002157', 'name': '正邦科技', 'market': 'SZ'},
    {'code': '002124', 'name': '天邦食品', 'market': 'SZ'},
    {'code': '603363', 'name': '傲农生物', 'market': 'SH'},
    {'code': '001201', 'name': '东瑞股份', 'market': 'SZ'},
    {'code': '605507', 'name': '江苏立华', 'market': 'SH'},
]

def get_realtime(secid):
    """获取个股实时行情"""
    url = f'https://push2.eastmoney.com/api/qt/stock/get'
    params = {
        'secid': f'{secid["market"]}.{secid["code"]}',
        'fields': 'f43,f44,f45,f46,f47,f48,f57,f58,f60,f107,f169,f170,f171',
    }
    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=10)
        data = resp.json().get('data', {})
        return {
            'code': secid['code'],
            'name': secid['name'],
            'price': data.get('f43', 0) / 100,          # 最新价
            'change_pct': data.get('f170', 0) / 100,    # 涨跌幅%
            'change_amt': data.get('f169', 0) / 100,    # 涨跌额
            'volume': data.get('f47', 0),                # 成交量(手)
            'amount': data.get('f48', 0),                # 成交额(元)
            'high': data.get('f44', 0) / 100,           # 最高
            'low': data.get('f45', 0) / 100,            # 最低
            'open': data.get('f46', 0) / 100,           # 今开
            'prev_close': data.get('f60', 0) / 100,     # 昨收
            'market_cap': data.get('f116', 0) / 100000000,  # 总市值(亿)
            'pe': data.get('f162', 0) / 100,            # 市盈率TTM
            'pb': data.get('f167', 0) / 100,             # 市净率
            'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }
    except Exception as e:
        return {'code': secid['code'], 'name': secid['name'], 'error': str(e)}


def get_index():
    """获取畜牧ETF 516670 行情（猪肉板块风向标）"""
    url = 'https://push2.eastmoney.com/api/qt/stock/get'
    params = {
        'secid': '1.516670',
        'fields': 'f43,f44,f45,f46,f47,f48,f57,f58,f60,f107,f169,f170',
    }
    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=10)
        data = resp.json().get('data', {})
        return {
            'code': '516670',
            'name': '畜牧ETF',
            'price': data.get('f43', 0) / 100,
            'change_pct': data.get('f170', 0) / 100,
            'change_amt': data.get('f169', 0) / 100,
            'volume': data.get('f47', 0),
            'amount': data.get('f48', 0),
            'high': data.get('f44', 0) / 100,
            'low': data.get('f45', 0) / 100,
            'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }
    except Exception as e:
        return {'code': '516670', 'name': '畜牧ETF', 'error': str(e)}


def fetch_all():
    """抓取所有数据"""
    results = {'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'stocks': [], 'etf': None}

    # 畜牧ETF
    etf = get_index()
    results['etf'] = etf
    print(f"  [{etf['code']}] {etf['name']}: {etf.get('price','N/A')} ({etf.get('change_pct','N/A')}%)")

    # 个股
    for s in STOCKS:
        time.sleep(random.uniform(0.3, 0.8))  # 礼貌性延迟
        d = get_realtime(s)
        results['stocks'].append(d)
        p = d.get('price', 'N/A')
        chg = d.get('change_pct', 'N/A')
        print(f"  [{d['code']}] {d['name']}: {p} ({chg}%)" if 'error' not in d else f"  [{d['code']}] {d['name']}: 失败 {d.get('error')}")

    return results


def main():
    print(f"\n{'='*50}")
    print(f"🐷 猪肉股数据抓取  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}\n")

    data = fetch_all()

    # 写入 JSON 文件（供前端页面读取）
    out_file = 'data/pork-stocks.json'
    with open(out_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 已保存到 {out_file}")

    # 写入 CSV（便于历史分析）
    import csv
    csv_file = 'data/pork-stocks.csv'
    rows = []
    for s in data['stocks']:
        rows.append({
            '时间': s['time'],
            '代码': s['code'],
            '名称': s['name'],
            '最新价': s.get('price', ''),
            '涨跌幅%': s.get('change_pct', ''),
            '涨跌额': s.get('change_amt', ''),
            '最高': s.get('high', ''),
            '最低': s.get('low', ''),
            '今开': s.get('open', ''),
            '昨收': s.get('prev_close', ''),
            '成交量(手)': s.get('volume', ''),
            '成交额(元)': s.get('amount', ''),
            '总市值(亿)': s.get('market_cap', ''),
            '市盈率TTM': s.get('pe', ''),
            '市净率': s.get('pb', ''),
        })

    if rows:
        with open(csv_file, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        print(f"✅ CSV 已保存到 {csv_file}")

if __name__ == '__main__':
    main()
