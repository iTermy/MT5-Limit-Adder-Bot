import discord
import MetaTrader5 as mt5
import re
import json
import datetime
import os

# Configuration files
CONFIG_FILE = 'config.json'
RISK_CONFIG_FILE = 'risk_config.json'

# Default risk configurations
DEFAULT_FIXED_LOTS = {
    "1": [0.50],
    "2": [0.25, 0.25],
    "3": [0.10, 0.20, 0.30],
    "4": [0.10, 0.15, 0.15, 0.20],
    "5": [0.10, 0.10, 0.10, 0.15, 0.15],
    "6": [0.10, 0.10, 0.10, 0.10, 0.10, 0.10],
    "7": [0.10, 0.10, 0.10, 0.10, 0.10, 0.10, 0.10],
    "8": [0.10, 0.10, 0.10, 0.10, 0.10, 0.10, 0.10, 0.10]
}

DEFAULT_RISK_PERCENTAGES = {
    "1": [10.0],
    "2": [5.0, 5.0],
    "3": [3.0, 3.0, 4.0],
    "4": [2.0, 2.0, 3.0, 3.0],
    "5": [1.5, 1.5, 2.0, 2.0, 3.0],
    "6": [1.0, 1.0, 1.5, 1.5, 2.0, 2.0],
    "7": [1.0, 1.0, 1.0, 1.0, 1.5, 1.5, 2.0],
    "8": [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 2.0, 2.0]
}

# Create default risk configuration
DEFAULT_CONFIG = {
    "active_config": "default",
    "mode": "risk",  # Can be "fixed" or "risk"
    "configs": {
        "default": {
            "fixed_lots": DEFAULT_FIXED_LOTS,
            "risk_percentages": DEFAULT_RISK_PERCENTAGES
        }
    }
}

# Load credentials
try:
    with open(CONFIG_FILE, 'r') as f:
        config = json.load(f)
    DISCORD_TOKEN = str(config.get('discord_token', ''))

    if not DISCORD_TOKEN:
        print("Warning: One or more required configuration values are empty in config.json")

except Exception as e:
    print(f"Error loading config.json: {str(e)}")
    exit()

if not DISCORD_TOKEN:
    print("Discord token not found in config.ini. Please enter it to proceed.")
    exit()


def is_forex_pair(symbol: str) -> bool:
    """Determine if the symbol is a forex pair."""
    currency_codes = {'USD', 'EUR', 'GBP', 'JPY', 'AUD', 'NZD', 'CAD', 'CHF', 'SGD', 'HKD'}

    if len(symbol) == 6:
        first_currency = symbol[:3]
        second_currency = symbol[3:]
        return first_currency in currency_codes and second_currency in currency_codes
    return False


def calculate_take_profit(symbol, entry_price, position, limit_index=0):
    """
    Calculate take profit price based on symbol type and configured value.
    Returns None if no take profit is set for the symbol.
    """
    # Get TP pips configuration
    tp_pips_config = risk_config.get("tp_pips")

    # If tp_pips is not a dictionary, no take profits are set
    if not isinstance(tp_pips_config, dict):
        return None

    # Determine the symbol category
    symbol_category = None

    # Check for specific symbol matches first
    specific_symbols = {
        "BTCUSD": "btc", "ETHUSD": "eth", "US30": "us30",
        "US500": "us500", "USTEC": "ustec", "DE40": "de40",
        "FR40": "fr40", "XAUUSD": "gold", "XAGUSD": "silver",
        "XTIUSD": "oil"
    }

    if symbol in specific_symbols:
        symbol_category = specific_symbols[symbol]
    elif symbol.endswith((".NYSE", ".NAS")):  # Stock
        symbol_category = symbol  # Use exact symbol for stocks
    elif is_forex_pair(symbol):
        symbol_category = "forex"

    # If we couldn't determine the category or no TP is set for this category
    if not symbol_category or symbol_category not in tp_pips_config or tp_pips_config[symbol_category] == 0:
        return None

    # Get symbol info to determine pip size
    symbol_info = mt5.symbol_info(symbol)
    if not symbol_info:
        print(f"Symbol info not found for {symbol}")
        return None

    # Get the configured value for this symbol category
    configured_value = float(tp_pips_config[symbol_category])

    # Calculate the TP price based on position direction and symbol type
    entry_price = float(entry_price)

    if symbol_category == "forex":
        # For forex pairs, the value is in pips
        # Determine pip size based on the symbol
        if symbol.endswith("JPY"):
            pip_size = 0.01
        else:
            pip_size = 0.0001

        if position.upper() == "LONG":
            tp_price = entry_price + (configured_value * pip_size)
        else:  # SHORT
            tp_price = entry_price - (configured_value * pip_size)
    else:
        # For non-forex symbols, the value is in dollars
        # Use the actual dollar value directly
        if position.upper() == "LONG":
            tp_price = entry_price + configured_value
        else:  # SHORT
            tp_price = entry_price - configured_value

    # Round the TP price to the correct number of digits
    if symbol_info:
        tp_price = round(tp_price, symbol_info.digits)

    return tp_price


def process_tp_command(message_content):
    """Process take profit commands"""
    parts = message_content.strip().lower().split()

    if len(parts) < 3:
        return "Invalid TP command format. Use: `tp <symbol_type> <value>` (e.g., `tp forex 10`)"

    symbol_type = parts[1]

    try:
        value = float(parts[2])

        # Initialize tp_pips as a dictionary if it's not already
        if not isinstance(risk_config.get("tp_pips"), dict):
            risk_config["tp_pips"] = {}

        # Add or update the TP pips configuration
        tp_pips_config = risk_config["tp_pips"]

        # Check for stock symbols
        if symbol_type.endswith((".nyse", ".nas")):
            symbol_type = symbol_type.upper()  # Ensure proper casing for stocks

            # If it's a new stock symbol, confirm with user
            if symbol_type not in tp_pips_config:
                return f"Stock symbol '{symbol_type}' not found in configuration. Reply with `add {symbol_type}` to add it."

        # Store the value - for non-forex, this is in dollars
        tp_pips_config[symbol_type] = value
        save_risk_config()

        # Determine message text based on symbol type
        if symbol_type == "forex":
            return f"Take profit for {symbol_type} set to {value} pips."
        else:
            return f"Take profit for {symbol_type} set to ${value}."

    except ValueError:
        return "Invalid value. Please use a number."


def process_add_command(message_content):
    """Process add command for stock symbols"""
    parts = message_content.strip().lower().split()

    if len(parts) < 2:
        return "Invalid add command format. Use: `add <stock_symbol>`"

    stock_symbol = parts[1].upper()

    # Check if it's a stock symbol format
    if not stock_symbol.endswith((".NYSE", ".NAS")):
        return f"Invalid stock symbol format. Symbol should end with .NYSE or .NAS"

    # Initialize tp_pips as a dictionary if it's not already
    if not isinstance(risk_config.get("tp_pips"), dict):
        risk_config["tp_pips"] = {}

    # Add the stock symbol to TP configuration with default value of 0 (no TP)
    tp_pips_config = risk_config["tp_pips"]
    tp_pips_config[stock_symbol] = 0
    save_risk_config()

    return f"Stock symbol '{stock_symbol}' added to configuration. Use `tp {stock_symbol.lower()} <pips>` to set the take profit."


def save_risk_config():
    """Save risk configuration to file"""
    try:
        with open(RISK_CONFIG_FILE, 'w') as f:
            json.dump(risk_config, f, indent=4)
        return True
    except Exception as e:
        print(f"Error saving risk configuration: {str(e)}")
        return False


# Default symbols for TP configuration
DEFAULT_TP_SYMBOLS = {
    "forex": 0,
    "btc": 0,
    "eth": 0,
    "us30": 0,
    "us500": 0,
    "ustec": 0,
    "dax": 0,
    "fr40": 0,
    "gold": 0,
    "silver": 0,
    "oil": 0
}

# Load or initialize risk configuration
try:
    if os.path.exists(RISK_CONFIG_FILE):
        # Load existing configuration
        with open(RISK_CONFIG_FILE, 'r') as f:
            risk_config = json.load(f)
        print(f"Loaded existing risk configuration from {RISK_CONFIG_FILE}")

        # Ensure default configuration exists
        if "configs" not in risk_config or "default" not in risk_config.get("configs", {}):
            print("Adding default configuration to existing config file")
            if "configs" not in risk_config:
                risk_config["configs"] = {}
            if "default" not in risk_config["configs"]:
                risk_config["configs"]["default"] = {
                    "fixed_lots": DEFAULT_FIXED_LOTS,
                    "risk_percentages": DEFAULT_RISK_PERCENTAGES
                }

        # Ensure tp_pips exists and is a dictionary
        if "tp_pips" not in risk_config or not isinstance(risk_config["tp_pips"], dict):
            risk_config["tp_pips"] = DEFAULT_TP_SYMBOLS.copy()
        else:
            # Ensure all default symbols exist in the tp_pips dictionary
            for symbol, value in DEFAULT_TP_SYMBOLS.items():
                if symbol not in risk_config["tp_pips"]:
                    risk_config["tp_pips"][symbol] = value

        save_risk_config()
    else:
        # Create new configuration file with defaults
        risk_config = DEFAULT_CONFIG
        risk_config["tp_pips"] = DEFAULT_TP_SYMBOLS.copy()
        with open(RISK_CONFIG_FILE, 'w') as f:
            json.dump(risk_config, f, indent=4)
        print(f"Created new risk configuration in {RISK_CONFIG_FILE}")
except Exception as e:
    print(f"Error with risk_config.json: {str(e)}")
    risk_config = DEFAULT_CONFIG
    risk_config["tp_pips"] = DEFAULT_TP_SYMBOLS.copy()
    try:
        with open(RISK_CONFIG_FILE, 'w') as f:
            json.dump(risk_config, f, indent=4)
    except:
        print("Failed to create default risk configuration")


# Initialize MetaTrader 5
if not mt5.initialize():
    print("MT5 initialization failed")
    exit()

# Create the Discord client
intents = discord.Intents.default()
intents.message_content = True  # Ensure message content is enabled
client = discord.Client(intents=intents)

# Get symbols
symbols = mt5.symbols_get()
AVAILABLE_SYMBOLS = {symbol.name for symbol in symbols} if symbols else set()

# Different from above
SYMBOL_MAPPINGS = {
    'gold': 'XAUUSD',
    'dax': 'DE40',
    'spx': 'US500',
    'nas': 'USTEC',
    'btc': 'BTCUSD',
    'eth': 'ETHUSD',
    'gu': 'GBPUSD',
    'uj': 'USDJPY',
    'silver': 'XAGUSD'
}


def calculate_lot_size(balance, risk_percentage, symbol, entry_price, sl):
    """
    Calculate lot size based on account balance, risk percentage, and symbol details.
    This handles various asset classes, including exotic forex pairs, metals, commodities, and indices.
    """
    # Ensure entry_price and sl are floats
    try:
        entry_price = float(entry_price)
        sl = float(sl)
    except ValueError as e:
        print(f"Error converting entry price or SL to float: {e}")
        return None

    # Calculate the risk amount based on the balance and risk percentage
    risk_amount = balance * (risk_percentage / 100)
    print(f"Risk Amount: {risk_amount}")

    # Retrieve symbol information
    symbol_info = mt5.symbol_info(symbol)
    if not symbol_info:
        print(f"Symbol info not found for {symbol}")
        return None

    # Contract size and tick size for the symbol
    contract_size = symbol_info.trade_contract_size
    tick_size = symbol_info.point
    tick_value = symbol_info.trade_tick_value  # Tick value per minimum price movement

    # Debug print for symbol info
    print(f"Symbol Info for {symbol}:")
    print(f"  Contract Size: {contract_size}")
    print(f"  Tick Size (Point): {tick_size}")
    print(f"  Tick Value: {tick_value}")
    print(f"  Min Volume: {symbol_info.volume_min}")
    print(f"  Max Volume: {symbol_info.volume_max}")
    print(f"  Volume Step: {symbol_info.volume_step}")

    # Calculate the stop loss in ticks
    stop_loss_ticks = abs(entry_price - sl) / tick_size
    print(f"Stop Loss in Ticks: {stop_loss_ticks}")

    # Calculate potential loss per lot based on stop loss and tick value
    potential_loss_per_lot = stop_loss_ticks * tick_value
    print(f"Potential Loss per Lot: {potential_loss_per_lot}")

    # Handle potential zero or extremely small values
    if potential_loss_per_lot == 0 or potential_loss_per_lot < 0.0001:
        print("Potential loss per lot is zero or negligible, check SL and entry price.")
        return None

    # Calculate the initial lot size based on risk amount and potential loss per lot
    lot_size = risk_amount / potential_loss_per_lot
    print(f"Calculated Lot Size before Rounding: {lot_size}")

    # Ensure lot size respects the broker's volume restrictions and rounds to nearest step
    if lot_size < symbol_info.volume_min:
        lot_size = symbol_info.volume_min
        print("Adjusted Lot Size to Min Volume")
    elif lot_size > symbol_info.volume_max:
        lot_size = symbol_info.volume_max
        print("Adjusted Lot Size to Max Volume")
    else:
        # Round down to nearest valid increment
        lot_size = (int(lot_size / symbol_info.volume_step) * symbol_info.volume_step)

    print(f"Final Calculated Lot Size for {symbol}: {lot_size}")
    return lot_size


def get_mapped_symbol(text: str) -> str or None:
    """
    Get the correct symbol from text using mappings and available symbols.

    Args:
        text (str): The input text to search for symbol

    Returns:
        str: Found symbol or None
    """
    text = text.lower()

    # First check for exact stock symbols (ending in .NYSE or .NAS)
    words = text.upper().split()
    for word in words:
        if word.endswith(('.NYSE', '.NAS')):
            if word in AVAILABLE_SYMBOLS:
                return word
            else:
                return None

    # Then check symbol mappings
    for key, mapped_symbol in SYMBOL_MAPPINGS.items():
        if key in text:
            return mapped_symbol if mapped_symbol in AVAILABLE_SYMBOLS else None

    # If no mapping found, look for direct symbol match
    for word in words:
        if word in AVAILABLE_SYMBOLS:
            return word

    # Check company name only using the first valid word
    skip_words = {'long', 'short', 'vth', 'hot', 'stops', 'comments', 'call', 'loss'}
    words = [
        word.lower() for word in text.split()
        if word.lower() not in skip_words and word.isalpha()
    ]
    if not words:
        return None
    word = words[0]
    # print("DEBUG: First word: ", word)
    matches = []

    # Check company names and descriptions for symbol
    for symbol in AVAILABLE_SYMBOLS:
        if symbol.endswith(('.NYSE', '.NAS')):
            if word in symbol.lower():
                # print(f"DEBUG: Found {word} in symbol {symbol}")
                matches.append(symbol)
                break
            else:
                symbol_info = mt5.symbol_info(symbol)
                if symbol_info and symbol_info.description:
                    if word in symbol_info.description.lower():
                        # print(f"DEBUG: Found {word} in description {symbol_info.description}")
                        matches.append(symbol)

    if len(matches) == 1:
        return matches[0]
    elif len(matches) > 1:
        raise ValueError(
            f"Several matches were found for {word}. Please specify the symbol with one of the following:\n * "
            f"{'\n* '.join(matches)}")
    return None


def get_friday_end_timestamp():
    today = datetime.datetime.now()
    days_until_friday = (4 - today.weekday()) % 7

    # If today is Friday, and it's past trading hours, move to next Friday
    if days_until_friday == 0 and today.hour >= 17:  # Assuming market closes at 5 PM
        days_until_friday = 7

    # Create datetime for Friday at end of trading day (typically 5 PM)
    friday = today + datetime.timedelta(days=days_until_friday)
    friday = friday.replace(hour=17, minute=0, second=0, microsecond=0)  # 5 PM

    # Get the timestamp in seconds (MT5 format)
    return int(friday.timestamp())


def parse_tm_signal(message):
    symbol = get_mapped_symbol(message)
    if not symbol:
        raise ValueError(f"Error: No valid trading symbol found in string")

    # Find position (long/short)
    position_match = re.search(r'\b(long|short)\b', message.lower())
    if not position_match:
        raise ValueError("Error: Position (long/short) not found in string")
    position = position_match.group(1).upper()

    # Get all numbers
    numbers = re.findall(r'(\d+\.?\d*)', message)
    if not numbers:
        raise ValueError("Error: No numbers found in string")
    if len(numbers) < 2:
        raise ValueError(
            "Error: Not enough numbers found in string. There must be at least 1 limit price and 1 stop loss.")

    # Convert large numbers if needed (Ex: AUDUSD is sometimes written as 61234 instead of 0.61234)
    if float(numbers[1]) > 30000 and symbol not in ["US30", "JP225", "BTCUSD", "USTEC"]:
        numbers = [str(float(num) / 100000) for num in numbers]

    # Last number is stop loss, rest are limits
    stop_loss = numbers[-1]
    limits = numbers[:-1]

    # Get comments and auto-keywords
    comments = ''
    comments_match = re.search(r'Comments:(.*?)(?=$|\n)', message, re.IGNORECASE)
    if comments_match:
        comments = comments_match.group(1).strip()
    if re.search("hot", message.lower()):
        comments = f"{comments} {', '.join("HOT")}"

    # Process expiry (Default to week if not major pair or vth (valid till hit))
    expiry = "WEEK"
    major_forex_pairs = ['EURUSD', 'USDJPY', 'GBPUSD', 'USDCHF', 'AUDUSD', 'USDCAD', 'NZDUSD']
    if symbol in major_forex_pairs:
        expiry = "DAY"
    if re.search("vth", message.lower()):
        expiry = "WEEK"
    if re.search("alien", message.lower()):
        expiry = "ALIEN"
    if re.search("day", message.lower()):
        expiry = "DAY"
    if re.search("week", message.lower()):
        expiry = 'WEEK'

    return [symbol, position, limits, stop_loss, expiry, comments]


def place_trade(order_type, order_kind, volume, symbol, entry_price, sl, tp=None, comment=None, expiration=None):
    """
    Places a trade on MT5 with the given parameters using either risk percentage or fixed lot size.
    """
    try:
        # Ensure price and sl are floats
        entry_price = float(entry_price)
        sl = float(sl)
        if tp is not None:
            tp = float(tp)

        # Set order type based on long/short
        order_type_mt5 = mt5.ORDER_TYPE_BUY_LIMIT if order_type.upper() == "LONG" else mt5.ORDER_TYPE_SELL_LIMIT

        # Set order action based on market/limit
        order_action_mt5 = mt5.TRADE_ACTION_PENDING if order_kind != "MARKET" else mt5.TRADE_ACTION_DEAL

        # Set expiration
        if expiration == "DAY":
            expiry_type = mt5.ORDER_TIME_DAY
            expiry = 0  # Not used for DAY
        elif expiration == "WEEK":
            expiry_type = mt5.ORDER_TIME_SPECIFIED
            expiry = get_friday_end_timestamp()
            print(f"Setting expiry to Friday timestamp: {expiry} ({datetime.datetime.fromtimestamp(expiry)})")
        else:
            expiry_type = mt5.ORDER_TIME_GTC
            expiry = 0  # Not used for GTC

        # Get current symbol info for price validation
        symbol_info = mt5.symbol_info(symbol)
        if not symbol_info:
            print(f"Symbol info not found for {symbol}")
            return False

        # Round prices to the correct number of digits
        digits = symbol_info.digits
        entry_price = round(entry_price, digits)
        sl = round(sl, digits)
        if tp is not None:
            tp = round(tp, digits)

        # Prepare order request
        request = {
            "action": order_action_mt5,
            "symbol": symbol,
            "volume": float(volume),  # Ensure volume is float
            "type": order_type_mt5,
            "price": entry_price,
            "sl": sl,
            "deviation": 20,
            "magic": 234000,
            "type_filling": mt5.ORDER_FILLING_IOC,
            "type_time": expiry_type,
            "expiration": expiry,
            "comment": comment
        }

        # Only add TP if it's not None (MetaTrader doesn't accept None for TP)
        if tp is not None:
            request["tp"] = tp

        # Log the request for debugging
        print("\nOrder Request:")
        for key, value in request.items():
            print(f"  {key}: {value}")

        # Check if price is within allowed range
        if symbol_info:
            print(f"Symbol Info - Ask: {symbol_info.ask}, Bid: {symbol_info.bid}")
            print(f"Symbol tick size: {symbol_info.trade_tick_size}")
            print(f"Symbol digits: {symbol_info.digits}")

        # Send order request
        result = mt5.order_send(request)

        if result is None:
            error_code = mt5.last_error()
            print(f"Order failed with error code: {error_code}")
            return False

        # Check the return code to determine if the order was successful
        # The TRADE_RETCODE_DONE is typically 10009
        print(f"Order result - retcode: {result.retcode}, description: {result.comment}")

        if result.retcode == mt5.TRADE_RETCODE_DONE:
            print(f"Order placed successfully: {result}")
            return True
        elif result.retcode == 10027:  # Likely a specific autotrading error code
            print(f"Order warning - retcode: {result.retcode}, comment: {result.comment}")
            print("This may be due to autotrading being disabled. Please check if autotrading is enabled in MT5.")
            return False
        else:
            print(f"Order failed: {result.retcode} - {result.comment}")
            return False

    except Exception as e:
        print(f"Unexpected error in place_trade: {str(e)}")
        return False


def get_volumes_for_limits(symbol, limits, stop_loss, position):
    """
    Calculate volumes for each limit based on current configuration
    """
    active_config_name = risk_config.get("active_config", "default")
    mode = risk_config.get("mode", "risk")

    # Get the active configuration
    active_config = risk_config.get("configs", {}).get(active_config_name, {})
    if not active_config:
        print(f"Warning: Configuration '{active_config_name}' not found. Using default.")
        active_config = risk_config.get("configs", {}).get("default", {})

    num_limits = str(len(limits))

    if num_limits not in ["1", "2", "3", "4", "5", "6", "7", "8"]:
        print(f"Warning: Unsupported number of limits: {num_limits}. Using default for 1 limit.")
        num_limits = "1"

    if mode == "fixed":
        # Get fixed lots configuration
        fixed_lots = active_config.get("fixed_lots", DEFAULT_FIXED_LOTS)
        volumes = fixed_lots.get(num_limits, [0.1] * int(num_limits))
        return volumes
    else:  # mode == "risk"
        # Get risk percentages configuration
        risk_percentages = active_config.get("risk_percentages", DEFAULT_RISK_PERCENTAGES)
        risk_percents = risk_percentages.get(num_limits, [1.0] * int(num_limits))

        # Get account balance
        account_info = mt5.account_info()
        if not account_info:
            print("Failed to get account info")
            return [0.1] * len(limits)

        balance = account_info.balance

        # Calculate volumes based on risk percentages
        volumes = []
        for i, limit in enumerate(limits):
            vol = calculate_lot_size(balance, risk_percents[i], symbol, float(limit), float(stop_loss))
            if vol is None:
                print(f"Warning: Failed to calculate lot size for limit {i + 1}. Using 0.1")
                vol = 0.1
            volumes.append(vol)

        return volumes


def process_config_command(message_content):
    """Process configuration commands"""
    parts = message_content.strip().lower().split()

    if len(parts) < 2:
        return "Invalid command format. Use: `config help` for available commands."

    command = parts[1]

    # Help command
    if command == "help":
        help_text = (
            "Available commands:\n"
            "`config list` - List all configurations\n"
            "`config show <name>` - Show details of a specific configuration\n"
            "`config set mode <fixed|risk>` - Set the active mode\n"
            "`config set active <name>` - Set the active configuration\n"
            "`config create <name>` - Create a new configuration\n"
            "`config delete <name>` - Delete a configuration\n"
            "`config set fixed <name> <limits> <values>` - Set fixed lot values\n"
            "`config set risk <name> <limits> <percentages>` - Set risk percentages\n"
            "Example: `config set fixed default 2 0.5 0.5`\n\n"
            "Take profit commands:\n"
            "`tp <symbol_type> <pips>` - Set take profit pips for a symbol type\n"
            "Example: `tp forex 10` - Sets 10 pips TP for forex pairs\n"
            "`add <stock_symbol>` - Add a stock symbol for TP configuration\n"
            "Example: `add AAPL.NAS` - Adds Apple stock to TP configuration"
        )
        return help_text

    # List configurations
    elif command == "list":
        active_config = risk_config.get("active_config", "default")
        mode = risk_config.get("mode", "risk")
        configs = list(risk_config.get("configs", {}).keys())

        if not configs:
            return "No configurations found."

        return f"Mode: {mode}\nActive: {active_config}\nConfigurations: {', '.join(configs)}"

    # Show configuration details
    elif command == "show" and len(parts) >= 3:
        config_name = parts[2]
        configs = risk_config.get("configs", {})

        if config_name not in configs:
            return f"Configuration '{config_name}' not found."

        config_data = configs[config_name]
        fixed_lots = config_data.get("fixed_lots", {})
        risk_percentages = config_data.get("risk_percentages", {})

        result = f"Configuration: {config_name}\n\nFixed lots:\n"
        for limit, values in sorted(fixed_lots.items(), key=lambda x: int(x[0])):
            result += f"{limit} limit(s): {' '.join(map(str, values))}\n"

        result += "\nRisk percentages:\n"
        for limit, values in sorted(risk_percentages.items(), key=lambda x: int(x[0])):
            result += f"{limit} limit(s): {' '.join(map(str, values))}%\n"

        return result

    # Set mode
    elif command == "set" and len(parts) >= 3 and parts[2] == "mode" and len(parts) >= 4:
        mode = parts[3]
        if mode not in ["fixed", "risk"]:
            return "Invalid mode. Use 'fixed' or 'risk'."

        risk_config["mode"] = mode
        save_risk_config()
        return f"Mode set to: {mode}"

    # Set active configuration
    elif command == "set" and len(parts) >= 3 and parts[2] == "active" and len(parts) >= 4:
        config_name = parts[3]
        configs = risk_config.get("configs", {})

        if config_name not in configs:
            return f"Configuration '{config_name}' not found."

        risk_config["active_config"] = config_name
        save_risk_config()
        return f"Active configuration set to: {config_name}"

    # Create configuration
    elif command == "create" and len(parts) >= 3:
        config_name = parts[2]
        configs = risk_config.get("configs", {})

        if config_name in configs:
            return f"Configuration '{config_name}' already exists."

        configs[config_name] = {
            "fixed_lots": DEFAULT_FIXED_LOTS.copy(),
            "risk_percentages": DEFAULT_RISK_PERCENTAGES.copy()
        }

        risk_config["configs"] = configs
        save_risk_config()
        return f"Configuration '{config_name}' created."

    # Delete configuration
    elif command == "delete" and len(parts) >= 3:
        config_name = parts[2]
        configs = risk_config.get("configs", {})

        if config_name not in configs:
            return f"Configuration '{config_name}' not found."

        if config_name == "default":
            return "Cannot delete the default configuration."

        del configs[config_name]

        # If active config was deleted, set to default
        if risk_config.get("active_config") == config_name:
            risk_config["active_config"] = "default"

        save_risk_config()
        return f"Configuration '{config_name}' deleted."

    # Set fixed lot values
    elif command == "set" and len(parts) >= 3 and parts[2] == "fixed" and len(parts) >= 5:
        config_name = parts[3]
        configs = risk_config.get("configs", {})

        if config_name not in configs:
            return f"Configuration '{config_name}' not found."

        try:
            num_limits = int(parts[4])
            if num_limits < 1 or num_limits > 8:
                return "Number of limits must be between 1 and 8."

            if len(parts) < num_limits + 5:
                return f"Expected {num_limits} values, got {len(parts) - 5}."

            values = [float(parts[5 + i]) for i in range(num_limits)]

            configs[config_name]["fixed_lots"][str(num_limits)] = values
            risk_config["configs"] = configs
            save_risk_config()

            return f"Fixed lot values for {num_limits} limit(s) in '{config_name}' set to: {' '.join(map(str, values))}"

        except ValueError:
            return "Invalid number format. Please use numbers for limits and values."

    # Set risk percentage values
    elif command == "set" and len(parts) >= 3 and parts[2] == "risk" and len(parts) >= 5:
        config_name = parts[3]
        configs = risk_config.get("configs", {})

        if config_name not in configs:
            return f"Configuration '{config_name}' not found."

        try:
            num_limits = int(parts[4])
            if num_limits < 1 or num_limits > 8:
                return "Number of limits must be between 1 and 8."

            if len(parts) < num_limits + 5:
                return f"Expected {num_limits} values, got {len(parts) - 5}."

            values = [float(parts[5 + i]) for i in range(num_limits)]

            configs[config_name]["risk_percentages"][str(num_limits)] = values
            risk_config["configs"] = configs
            save_risk_config()

            return f"Risk percentage values for {num_limits} limit(s) in '{config_name}' set to: {' '.join(map(str, values))}%"

        except ValueError:
            return "Invalid number format. Please use numbers for limits and values."

    else:
        return "Invalid command. Use: `config help` for available commands."


def process_tp_config_command():
    """Display the current take profit configuration"""
    tp_pips_config = risk_config.get("tp_pips", {})

    if not isinstance(tp_pips_config, dict) or not tp_pips_config:
        return "No take profit configuration found."

    # Organize TP settings by category
    forex_symbols = []
    other_symbols = []
    stock_symbols = []

    for symbol, value in tp_pips_config.items():
        if symbol.endswith((".NYSE", ".NAS")):
            stock_symbols.append(f"{symbol}: ${value}")
        elif symbol == "forex":
            forex_symbols.append(f"{symbol}: {value} pips")
        else:
            other_symbols.append(f"{symbol}: {value} dollars")

    # Sort all lists
    forex_symbols.sort()
    other_symbols.sort()
    stock_symbols.sort()

    result = "**Take Profit Configuration**\n\n"

    # Add forex symbols section
    if forex_symbols:
        result += "**Forex Pairs:**\n"
        for item in forex_symbols:
            result += f"• {item}\n"

    # Add other symbols section
    if other_symbols:
        result += "\n**Other Symbols:**\n"
        for item in other_symbols:
            result += f"• {item}\n"

    # Add stock symbols section
    if stock_symbols:
        result += "\n**Stock Symbols:**\n"
        for item in stock_symbols:
            result += f"• {item}\n"

    result += "\nUse `tp <symbol_type> <value>` to change settings."
    result += "\n(Forex uses pips, other symbols use dollar values)"

    return result


@client.event
async def on_ready():
    print(f'Logged in as {client.user.name} ({client.user.id})')
    print(f'Active configuration: {risk_config.get("active_config", "default")}')
    print(f'Mode: {risk_config.get("mode", "risk")}')
    print('------')


@client.event
async def on_message(message):
    if message.author == client.user:
        return

    content = message.content.strip()

    # Process configuration commands
    if content.lower().startswith("config "):
        response = process_config_command(content)
        await message.channel.send(response)
        return

    # Process take profit configuration command
    if content.lower() == "tp config":
        response = process_tp_config_command()
        await message.channel.send(response)
        return

    # Process take profit commands
    if content.lower().startswith("tp "):
        response = process_tp_command(content)
        await message.channel.send(response)
        return

    # Process add commands for stock symbols
    if content.lower().startswith("add "):
        response = process_add_command(content)
        await message.channel.send(response)
        return

    # Process trading signals
    try:
        trade_signal = parse_tm_signal(content)
        symbol = trade_signal[0]
        position = trade_signal[1]
        limits = trade_signal[2]
        stop_loss = trade_signal[3]
        expiry = trade_signal[4]
        comments = trade_signal[5]

        num_limits = len(limits)

        # Calculate volumes for each limit
        volumes = get_volumes_for_limits(symbol, limits, stop_loss, position)

        # Place trades
        trades_placed = 0
        for i, limit in enumerate(limits):
            if i < len(volumes):
                volume = volumes[i]
                # Calculate take profit for this limit
                tp = calculate_take_profit(symbol, limit, position, i)

                success = place_trade(
                    order_type=position,
                    order_kind="LIMIT",
                    symbol=symbol,
                    volume=volume,
                    entry_price=limit,
                    sl=stop_loss,
                    tp=tp,
                    comment=comments,
                    expiration=expiry
                )
                if success:
                    trades_placed += 1

        # Report on trade placement
        active_config = risk_config.get("active_config", "default")
        mode = risk_config.get("mode", "risk")
        await message.channel.send(
            f"Placed {trades_placed}/{num_limits} trades using {mode} mode with '{active_config}' configuration")

    except ValueError as e:
        await message.channel.send(f"Error: {str(e)}")
    except Exception as e:
        print(f"Unexpected error: {str(e)}")
        await message.channel.send(f"Unexpected error: {str(e)}")


# Start the Discord bot
client.run(DISCORD_TOKEN)

# Shutdown MetaTrader 5 on exit
mt5.shutdown()
