"""
MEXC Trading Bot with Automated Stop Loss and Trailing Take Profit
Receives webhook signals from TradingView and executes trades automatically
"""

# =============================================================================
# IMPORTS
# =============================================================================
import json
import threading
import time
import sys
from decimal import Decimal, getcontext, ROUND_DOWN
from flask import Flask, request, jsonify
import ccxt

# =============================================================================
# CONFIGURATION - STRATEGY PARAMETERS
# =============================================================================
INITIAL_STOP_LOSS_PCT = Decimal('0.01')        # 1%
BREAKEVEN_TRIGGER_PCT = Decimal('2')           # 2%
TRAILING_PROFIT_ACTIVATION_PCT = Decimal('4')  # 4%
TRAILING_PROFIT_EXIT_PCT = Decimal('2')        # 2%
TAKE_PROFIT_TARGET_PCT = Decimal('1.04')       # 4%

# =============================================================================
# TERMINAL COLORS
# =============================================================================
class Colors:
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    BOLD = '\033[1m'
    ENDC = '\033[0m'

# =============================================================================
# FLASK
# =============================================================================
app = Flask(__name__)
getcontext().prec = 28

# =============================================================================
# MEXC API (CCXT)
# =============================================================================
from config import api_key, api_secret

exchange = ccxt.mexc({
    'apiKey': api_key,
    'secret': api_secret,
    'enableRateLimit': True,
    'options': {'defaultType': 'spot'}
})

exchange.load_markets()

# =============================================================================
# GLOBAL POSITIONS
# =============================================================================
open_positions = {}

# =============================================================================
# WEBHOOK
# =============================================================================
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json()
        action = data.get('action')
        symbol = data.get('ticker').upper()

        if action == 'buy':
            return buy(symbol)
        elif action == 'sell':
            return sell(symbol)
        else:
            return jsonify({'error': 'Invalid action'}), 400

    except Exception as e:
        return jsonify({'error': str(e)}), 500

# =============================================================================
# HELPERS
# =============================================================================
def get_available_balance(currency):
    balance = exchange.fetch_balance()
    return Decimal(str(balance['free'].get(currency, 0)))

def get_market_info(symbol):
    market = exchange.markets[symbol]
    min_amount = Decimal(str(market['limits']['amount']['min']))
    min_cost = Decimal(str(market['limits']['cost']['min']))
    amount_precision = market['precision']['amount']
    price_precision = market['precision']['price']
    return min_amount, min_cost, amount_precision, price_precision

# =============================================================================
# BUY
# =============================================================================
def buy(symbol):
    try:
        usdt_balance = get_available_balance('USDT')
        if usdt_balance <= 0:
            return jsonify({'error': 'No USDT balance'}), 400

        min_amount, min_cost, _, _ = get_market_info(symbol)
        if usdt_balance < min_cost:
            return jsonify({'error': 'Below minimum order cost'}), 400

        order = exchange.create_market_buy_order(symbol, float(usdt_balance))
        avg_price = Decimal(str(order['average'] or order['price']))
        filled_amount = Decimal(str(order['filled']))

        initial_sl = avg_price * (Decimal('1') - INITIAL_STOP_LOSS_PCT)

        open_positions[symbol] = {
            'symbol': symbol,
            'entry_price': avg_price,
            'amount': filled_amount,
            'current_sl': initial_sl,
            'peak_price': avg_price,
            'trail_started': False,
            'breakeven': False,
            'status': 'open'
        }

        threading.Thread(target=monitor_position, args=(symbol,), daemon=True).start()

        return jsonify({'status': 'BUY OK', 'price': str(avg_price)})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

# =============================================================================
# SELL
# =============================================================================
def sell(symbol):
    try:
        position = open_positions.get(symbol)
        if not position:
            return jsonify({'error': 'No open position'}), 400

        execute_sell(symbol, position['amount'])
        del open_positions[symbol]

        return jsonify({'status': 'SELL OK'})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

def execute_sell(symbol, amount):
    exchange.create_market_sell_order(symbol, float(amount))
    print(f"{Colors.FAIL}SELL EXECUTED {symbol}{Colors.ENDC}")

# =============================================================================
# MONITOR POSITION
# =============================================================================
def monitor_position(symbol):
    print(f"{Colors.OKGREEN}Monitoring {symbol}{Colors.ENDC}")

    while symbol in open_positions:
        try:
            pos = open_positions[symbol]
            ticker = exchange.fetch_ticker(symbol)
            price = Decimal(str(ticker['last']))

            if price > pos['peak_price']:
                pos['peak_price'] = price

            profit_pct = (price - pos['entry_price']) / pos['entry_price'] * 100

            # STOP LOSS
            if price <= pos['current_sl']:
                execute_sell(symbol, pos['amount'])
                del open_positions[symbol]
                break

            # BREAKEVEN
            if not pos['breakeven'] and profit_pct >= BREAKEVEN_TRIGGER_PCT:
                pos['current_sl'] = pos['entry_price']
                pos['breakeven'] = True

            # TRAILING START
            if not pos['trail_started'] and profit_pct >= TRAILING_PROFIT_ACTIVATION_PCT:
                pos['trail_started'] = True

            # TRAILING EXIT
            if pos['trail_started']:
                retrace = (pos['peak_price'] - price) / pos['peak_price'] * 100
                if retrace >= TRAILING_PROFIT_EXIT_PCT:
                    execute_sell(symbol, pos['amount'])
                    del open_positions[symbol]
                    break

            sys.stdout.write(
                f"\r{Colors.OKBLUE}{symbol} "
                f"Price:{price} "
                f"SL:{pos['current_sl']} "
                f"P/L:{profit_pct:.2f}%{Colors.ENDC}"
            )
            sys.stdout.flush()

            time.sleep(0.5)

        except Exception as e:
            print(f"\nMonitor error: {e}")
            time.sleep(1)

# =============================================================================
# RUN
# =============================================================================
if __name__ == "__main__":
    app.run(port=5000, debug=False)
