"""
Kronos 回测服务
Flask 后端：接收前端参数 → 调用引擎 → 返回 JSON
"""

from flask import Flask, request, jsonify, send_from_directory
import os
import sys
from datetime import datetime, timedelta

# 确保同目录的 kronos_engine 可被导入
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kronos_engine import run_kronos

app = Flask(__name__, static_folder='.')
APP_DIR = os.path.dirname(os.path.abspath(__file__))

# ─── CORS（允许前端跨域调用）──
@app.after_request
def add_cors(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response

# ─── API: 运行回测 ────────────────────────────────────────────────────────────
@app.route('/api/kronos/backtest', methods=['POST', 'OPTIONS'])
def api_backtest():
    """
    POST JSON body:
    {
        "stock": "000858",
        "start": "2025-01-01",
        "end": "2026-04-30",
        "lookback": 20,
        "temperature": 0.7,
        "pred_len": 30
    }
    """
    if request.method == 'OPTIONS':
        return '', 204

    data = request.get_json()
    if not data:
        return jsonify({'error': '请求体为空'}), 400

    stock = data.get('stock', '').strip()
    start = data.get('start', '').strip()
    end = data.get('end', '').strip()

    if not stock or not start or not end:
        return jsonify({'error': '缺少必填字段：stock / start / end'}), 400

    lookback = int(data.get('lookback', 20))
    temperature = float(data.get('temperature', 0.7))
    pred_len = int(data.get('pred_len', 30))

    try:
        result = run_kronos(
            stock_code=stock,
            start_date=start,
            end_date=end,
            lookback=lookback,
            temperature=temperature,
            pred_len=pred_len
        )
        return jsonify(result), 200
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': f'回测失败：{str(e)}'}), 500

def default_start():
    return (datetime.now() - timedelta(days=300)).strftime('%Y-%m-%d')

def default_end():
    return datetime.now().strftime('%Y-%m-%d')

# ─── API: 常用股票快捷选项 ────────────────────────────────────────────────────
@app.route('/api/kronos/presets', methods=['GET'])
def api_presets():
    return jsonify({
        'stocks': [
            {'code': '000858', 'name': '五粮液', 'sector': '白酒'},
            {'code': '600519', 'name': '贵州茅台', 'sector': '白酒'},
            {'code': '002714', 'name': '牧原股份', 'sector': '猪肉'},
            {'code': '000876', 'name': '新希望', 'sector': '猪肉'},
            {'code': '002330', 'name': '得利斯', 'sector': '猪肉'},
            {'code': '603363', 'name': '傲农生物', 'sector': '猪肉'},
            {'code': '002567', 'name': '唐人神', 'sector': '猪肉'},
            {'code': '002124', 'name': '天邦食品', 'sector': '猪肉'},
            {'code': '002505', 'name': '大北农', 'sector': '猪肉'},
            {'code': '000735', 'name': '罗牛山', 'sector': '猪肉'},
            {'code': '516670', 'name': '畜牧ETF', 'sector': 'ETF'},
            {'code': '601919', 'name': '中远海控', 'sector': '航运'},
            {'code': '600900', 'name': '长江电力', 'sector': '电力'},
            {'code': '600886', 'name': '国投电力', 'sector': '电力'},
            {'code': '601985', 'name': '中国核电', 'sector': '电力'},
            {'code': '002460', 'name': '赣锋锂业', 'sector': '有色'},
            {'code': '000630', 'name': '铜陵有色', 'sector': '有色'},
            {'code': '601600', 'name': '中国铝业', 'sector': '有色'},
        ],
        'default_range': {
            'start': default_start(),
            'end': default_end()
        }
    })

# ─── 静态页面路由 ─────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return send_from_directory(APP_DIR, 'index.html')

@app.route('/kronos')
@app.route('/kronos.html')
def kronos_page():
    return send_from_directory(APP_DIR, 'kronos.html')

@app.route('/pork.html')
def pork_page():
    return send_from_directory(APP_DIR, 'pork.html')

# ─── 启动 ─────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    print("=" * 50)
    print("Kronos 回测服务 启动中...")
    print("  本地访问: http://127.0.0.1:5555")
    print("  Kronos 页面: http://127.0.0.1:5555/kronos")
    print("=" * 50)
    app.run(host='0.0.0.0', port=5555, debug=True)
