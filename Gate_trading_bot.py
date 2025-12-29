"""
Gate.io Trading Bot with Automated Stop Loss and Trailing Take Profit
Receives webhook signals from TradingView and executes trades automatically
"""

# ============================================================================
# IMPORTS
# ============================================================================
import json
from decimal import Decimal, getcontext, ROUND_DOWN
from flask import Flask, request, jsonify
import gate_api
from gate_api.exceptions import ApiException, GateApiException
import threading
import time
import sys

# ============================================================================
# CONFIGURATION - TRADING STRATEGY PARAMETERS
# ============================================================================
# All percentage values are in decimal format (e.g., 0.01 = 1%)

INITIAL_STOP_LOSS_PCT = Decimal('0.01')        # 1% below entry price
BREAKEVEN_TRIGGER_PCT = Decimal('2')           # Move SL to breakeven after 2% profit
TRAILING_PROFIT_ACTIVATION_PCT = Decimal('4')  # Activate TTP after 4% profit
TRAILING_PROFIT_EXIT_PCT = Decimal('2')        # Exit when price drops 2% from peak
TAKE_PROFIT_TARGET_PCT = Decimal('1.04')       # Visual TP target at 4% profit

# ============================================================================
# TERMINAL COLORS
# ============================================================================
class Colors:
    HEADER = '\033[95m'      # Magenta
    OKBLUE = '\033[94m'      # Blue
    OKCYAN = '\033[96m'      # Cyan
    OKGREEN = '\033[92m'     # Green
    WARNING = '\033[93m'     # Yellow
    FAIL = '\033[91m'        # Red
    ENDC = '\033[0m'         # Reset
    BOLD = '\033[1m'         # Bold
    UNDERLINE = '\033[4m'    # Underline

# ============================================================================
# FLASK APP SETUP
# ============================================================================
app = Flask(__name__)
getcontext().prec = 28

# ============================================================================
# API CREDENTIALS & CLIENT SETUP
# ============================================================================
from config import api_key, api_secret

configuration = gate_api.Configuration(
    host="https://api.gateio.ws/api/v4",
    key=api_key,
    secret=api_secret
)

api_client = gate_api.ApiClient(configuration)
spot_api = gate_api.SpotApi(api_client)

# ============================================================================
# GLOBAL VARIABLES
# ============================================================================
open_positions = {}  # Stores all active trading positions

# ============================================================================
# WEBHOOK ENDPOINT - Receives trading signals
# ============================================================================
@app.route('/webhook', methods=['POST'])
def webhook():
    """
    Main webhook endpoint that receives trading signals from TradingView
    Expected payload: {"action": "buy/sell", "ticker": "BTC/USDT", "price": 50000}
    """
    print(f"\n{Colors.HEADER}{Colors.BOLD}{'=' * 50}{Colors.ENDC}", flush=True)
    print(f"{Colors.HEADER}{Colors.BOLD}WEBHOOK CALLED!{Colors.ENDC}", flush=True)
    print(f"{Colors.HEADER}{Colors.BOLD}{'=' * 50}{Colors.ENDC}\n", flush=True)

    try:
        data = request.get_json()
        print(f"{Colors.OKCYAN}Received data: {data}{Colors.ENDC}", flush=True)

        action = data.get('action')
        ticker = data.get('ticker')
        price = data.get('price')

        if action == 'buy':
            return buy(ticker, price)
        elif action == 'sell':
            return sell(ticker, price)
        else:
            return jsonify({'message': 'Invalid action specified'}), 400

    except Exception as e:
        return jsonify({'message': f'Internal Server Error: {str(e)}'}), 500

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_available_balance(currency):
    """Get available balance for a specific currency"""
    try:
        accounts = spot_api.list_spot_accounts(currency=currency)
        for account in accounts:
            if account.currency == currency:
                return Decimal(account.available)
        return Decimal('0')
    except Exception as e:
        raise Exception('Failed to fetch balance: ' + str(e))


def get_minimum_order_size(currency_pair):
    """Get minimum order size and precision details for a trading pair"""
    try:
        market = spot_api.get_currency_pair(currency_pair)

        min_base_amount = Decimal(market.min_base_amount)
        min_quote_amount = Decimal(market.min_quote_amount)
        amount_precision = int(market.amount_precision)
        price_precision = int(market.precision)

        print(f"Market details {currency_pair}:")
        print(f"amount_precision: {amount_precision}")
        print(f"price_precision: {price_precision}")

        return min_base_amount, min_quote_amount, amount_precision, price_precision

    except Exception as e:
        raise Exception(f"Failed to fetch minimum order size for {currency_pair}: {str(e)}")

# ============================================================================
# BUY FUNCTION - Executes buy orders
# ============================================================================

def buy(ticker, price):
    """
    Execute a buy order using all available USDT balance
    Sets initial stop loss and starts position monitoring
    """
    try:
        currency_pair = ticker.replace('/', '_').upper()

        # Get available USDT balance
        usdt_balance = get_available_balance('USDT')
        if usdt_balance <= 0:
            print('Insufficient USDT balance to place buy order')
            return jsonify({'message': 'Insufficient USDT balance to place buy order'}), 400

        # Validate price
        if price is None or Decimal(str(price)) <= 0:
            print(f'Invalid price: {price}. Cannot proceed with buy order.')
            return jsonify({'message': f'Invalid price: {price}. Cannot proceed with buy order.'}), 400

        # Get market precision requirements
        min_base_amount, min_quote_amount, amount_precision, price_precision = get_minimum_order_size(currency_pair)

        total = usdt_balance

        # Validate minimum order size
        if total < min_quote_amount:
            print(f'Available USDT balance {total} is less than minimum quote amount {min_quote_amount}')
            return jsonify({
                'message': f'Available USDT balance {total} is less than minimum quote amount {min_quote_amount}'
            }), 400

        if total <= 0:
            print('Total USDT amount is zero. Cannot place order.')
            return jsonify({'message': 'Total USDT amount is zero. Cannot place order.'}), 400

        # Format total with correct precision
        total_precision_format = Decimal('1e-{0}'.format(price_precision))
        total = total.quantize(total_precision_format, rounding=ROUND_DOWN)
        total_str = '{:.{prec}f}'.format(total, prec=price_precision)

        # Display order information
        print(f"Market details {currency_pair}:")
        print(f"Ticker: {ticker}")
        print(f"Price: {price}")
        print(f"USDT balance: {usdt_balance}")
        print(f"Total (USDT) to spend: {total_str}")
        print(f"Minimum base amount: {min_base_amount}")

        # Create market buy order
        order = gate_api.Order(
            currency_pair=currency_pair,
            type="market",
            side="buy",
            amount=total_str,
            time_in_force="ioc"
        )

        # Execute the order
        response = spot_api.create_order(order)
        order_id = response.id

        # Wait for order to be filled
        order_filled = False
        max_retries = 5
        retries = 0

        while not order_filled and retries < max_retries:
            order_details = spot_api.get_order(order_id, currency_pair)

            if order_details.status == 'closed':
                order_filled = True
                break
            else:
                retries += 1
                time.sleep(1)

        if not order_filled:
            print('Order was not filled in time')
            return jsonify({'message': 'Order was not filled in time'}), 400

        # Get fill details
        avg_price = Decimal(order_details.avg_deal_price)
        filled_amount = Decimal(order_details.filled_amount)
        entry_price = avg_price

        # Calculate initial stop loss using configured percentage
        initial_stop_loss_price = entry_price * (Decimal('1') - INITIAL_STOP_LOSS_PCT)

        print(f"Order executed at price {entry_price}, initial SL set at {initial_stop_loss_price}")

        # Create position record
        position = {
            'currency_pair': currency_pair,
            'entry_price': entry_price,
            'amount': filled_amount,
            'initial_stop_loss_price': initial_stop_loss_price,
            'current_stop_loss_price': initial_stop_loss_price,
            'status': 'open',
            'peak_price': entry_price,
            'trail_started': False,
            'adjusted_to_breakeven': False,
        }

        # Store position
        open_positions[currency_pair] = position

        # Start monitoring thread
        monitor_thread = threading.Thread(target=monitor_position, args=(currency_pair,))
        monitor_thread.start()

        return jsonify({'message': 'Buy order placed', 'order': response.to_dict()}), 200

    except GateApiException as e:
        print(f"Error placing buy order: {e}")
        return jsonify({'message': 'Error placing buy order', 'details': str(e)}), e.status
    except Exception as e:
        print(f"Error in buy function: {e}")
        return jsonify({'message': 'Error placing buy order: ' + str(e)}), 500

# ============================================================================
# SELL FUNCTION - Executes sell orders
# ============================================================================

def sell(ticker, price):
    """
    Execute a manual sell order from webhook signal
    Closes the position and removes it from monitoring
    """
    try:
        currency_pair = ticker.replace('/', '_')

        # Check if position exists
        position = open_positions.get(currency_pair)
        if not position:
            return jsonify({'message': f'No open position for {currency_pair} to sell'}), 400

        # Execute market sell
        execute_market_sell(currency_pair, position['amount'])

        # Update position status
        position['status'] = 'closed'

        # Remove position from tracking
        del open_positions[currency_pair]

        return jsonify({'message': 'Sell order placed'}), 200

    except GateApiException as e:
        error_body = e.body
        try:
            error_json = json.loads(error_body)
            error_message = error_json.get('message', '')
            label = error_json.get('label', '')
        except Exception:
            error_message = error_body
            label = ''
        return jsonify({
            'message': 'Error placing sell order',
            'error_label': label,
            'details': error_message
        }), e.status
    except Exception as e:
        return jsonify({'message': 'Error placing sell order: ' + str(e)}), 500

# ============================================================================
# EXECUTE MARKET SELL - Helper function to sell positions
# ============================================================================

def execute_market_sell(currency_pair, amount):
    """Execute a market sell order for a given amount"""
    try:
        # Get market precision
        _, _, amount_precision, _ = get_minimum_order_size(currency_pair)
        amount_precision_format = Decimal('1e-{0}'.format(amount_precision))
        amount_decimal = Decimal(amount).quantize(amount_precision_format, rounding=ROUND_DOWN)

        # Verify balance
        current_balance = get_available_balance(currency_pair.split('_')[0])
        if current_balance < amount_decimal:
            if current_balance >= Decimal(amount) - amount_decimal:
                amount_decimal = current_balance
                print(f"Adjusted sell amount to available balance: {amount_decimal}")
            else:
                print(f"Insufficient balance. Available: {current_balance}, Required: {amount_decimal}")
                return

        # Create and execute sell order
        order = gate_api.Order(
            currency_pair=currency_pair,
            type="market",
            side="sell",
            amount=str(amount_decimal),
            time_in_force="ioc"
        )
        response = spot_api.create_order(order)
        print(f"Market sell order executed for {currency_pair}")

    except ApiException as e:
        print(f"API Exception when selling {currency_pair}: {e}")
    except Exception as e:
        print(f"Error executing market sell for {currency_pair}: {e}")

# ============================================================================
# POSITION MONITORING - Automated SL and TTP management
# ============================================================================

def monitor_position(currency_pair):
    """
    Continuously monitor position and manage stop loss and take profit

    Strategy:
    1. Initial SL: Set at INITIAL_STOP_LOSS_PCT below entry
    2. Breakeven: Move SL to entry after BREAKEVEN_TRIGGER_PCT profit
    3. TTP Activation: Start trailing after TRAILING_PROFIT_ACTIVATION_PCT profit
    4. TTP Exit: Sell if price drops TRAILING_PROFIT_EXIT_PCT from peak
    """
    global open_positions
    position = open_positions.get(currency_pair)
    if not position:
        print(f"No open position for {currency_pair} to monitor.")
        return

    print(f"Started monitoring position for {currency_pair}")

    while position['status'] == 'open':
        try:
            # Fetch current market price
            ticker = spot_api.list_tickers(currency_pair=currency_pair)[0]
            current_price = Decimal(ticker.last)

            # Track peak price for trailing
            if current_price > position['peak_price']:
                position['peak_price'] = current_price

            # Calculate profit/loss percentage
            price_change = (current_price - position['entry_price']) / position['entry_price'] * 100

            # ================================================================
            # STOP LOSS CHECK - Exit if SL is hit
            # ================================================================
            if current_price <= position['current_stop_loss_price']:
                print(f"\nPrice hit SL target at {current_price} for {currency_pair}. Selling...")
                execute_market_sell(position['currency_pair'], position['amount'])
                position['status'] = 'closed'
                print(f"Position closed for {currency_pair}")
                del open_positions[currency_pair]
                break

            # ================================================================
            # BREAKEVEN ADJUSTMENT - Move SL to entry after profit threshold
            # ================================================================
            if not position['adjusted_to_breakeven'] and price_change >= BREAKEVEN_TRIGGER_PCT:
                position['current_stop_loss_price'] = position['entry_price']
                position['adjusted_to_breakeven'] = True
                print(f"\nPrice moved up {BREAKEVEN_TRIGGER_PCT}% from entry. Adjusted SL to entry price for {currency_pair}")

            # ================================================================
            # TRAILING TAKE PROFIT ACTIVATION - Start trailing at profit threshold
            # ================================================================
            if not position['trail_started'] and price_change >= TRAILING_PROFIT_ACTIVATION_PCT:
                position['trail_started'] = True
                print(f"\nPrice reached {TRAILING_PROFIT_ACTIVATION_PCT}% profit for {currency_pair}. Starting trailing take profit")

            # ================================================================
            # TRAILING TAKE PROFIT EXIT - Sell on retracement from peak
            # ================================================================
            if position['trail_started']:
                retracement = (position['peak_price'] - current_price) / position['peak_price'] * 100
                if retracement >= TRAILING_PROFIT_EXIT_PCT:
                    print(f"\nPrice retraced {TRAILING_PROFIT_EXIT_PCT}% from peak. Selling {currency_pair}")
                    execute_market_sell(position['currency_pair'], position['amount'])
                    position['status'] = 'closed'
                    print(f"Position closed for {currency_pair}")
                    del open_positions[currency_pair]
                    break

            # ================================================================
            # DISPLAY - Show current position status with colors
            # ================================================================
            profit_pct = ((current_price - position['entry_price']) / position['entry_price']) * 100
            tp_target = position['entry_price'] * TAKE_PROFIT_TARGET_PCT

            monitoring_message = (
                f"{Colors.OKBLUE}Current price: {Colors.BOLD}{current_price}{Colors.ENDC} | "
                f"{Colors.OKCYAN}Entry: {position['entry_price']}{Colors.ENDC} | "
                f"{Colors.FAIL}SL: {position['current_stop_loss_price']}{Colors.ENDC} | "
                f"{Colors.OKGREEN}Peak: {position['peak_price']}{Colors.ENDC} | "
                f"{Colors.WARNING}TP Target: {tp_target:.5f}{Colors.ENDC} | "
                f"{Colors.OKGREEN if profit_pct >= 0 else Colors.FAIL}P/L: {profit_pct:+.2f}%{Colors.ENDC} | "
                f"{Colors.BOLD}{Colors.OKGREEN if position['trail_started'] else Colors.WARNING}TTP: {'Activated' if position['trail_started'] else 'Inactive'}{Colors.ENDC}"
            )

            sys.stdout.write(f"\r{monitoring_message}")
            sys.stdout.flush()

            time.sleep(0.5)

        except Exception as e:
            print(f"\nError in monitoring position {currency_pair}: {e}")
            time.sleep(0.5)

# ============================================================================
# START FLASK SERVER
# ============================================================================

if __name__ == '__main__':
    app.run(debug=True, port=5000, use_reloader=False)
