# Trading Bot Project

A cryptocurrency trading bot for Gate.io exchange.

## Prerequisites

- Python 3.7 or higher
- Gate.io account with API credentials

## Setup Instructions

### 1. Clone the Repository

```bash
git clone <your-repository-url>
cd trading-bot-project
```

### 2. Add Your Gate.io API Credentials

Open `config.py` and replace the placeholder values with your actual Gate.io API credentials:

```python
api_key = "your_actual_api_key_here"
api_secret = "your_actual_secret_key_here"
```

**Important:** Never commit your actual API keys to git. The `config.py` file is already included in `.gitignore`.

### 3. Create Virtual Environment

```bash
python3 -m venv venv
```

### 4. Activate Virtual Environment

**On macOS/Linux:**

```bash
source venv/bin/activate
```

**On Windows:**

```bash
venv\Scripts\activate
```

### 5. Install Dependencies

```bash
pip install -r requirements.txt
```

### 6. Run the Bot

```bash
python Gate_trading_bot.py
```

## Dependencies

- `secret` - Secrets management
- `flask` - Web framework
- `gate-api` - Gate.io API client
- `requests` - HTTP library

## Project Structure

```
trading-bot-project/
├── Gate_trading_bot.py  # Main trading bot application
├── config.py            # API credentials configuration
├── requirements.txt     # Python dependencies
├── .gitignore          # Git ignore rules
├── venv/               # Virtual environment (not tracked in git)
└── README.md           # This file
```

## Security Notes

- Never share your API keys
- Keep `config.py` private and never commit it to version control
- Use API keys with appropriate permissions only
- Consider using environment variables for production deployments

## License

This project is for educational purposes only.

## Resources

- Website: [fomad.net](https://fomad.net)
- YouTube: [Profit with Python](https://www.youtube.com/@ProfitWithPython)
- Contact: info@fomad.net

## Disclaimer

This trading bot is provided for educational purposes only. Trading cryptocurrencies involves substantial risk of loss. Always test thoroughly and use at your own risk.
