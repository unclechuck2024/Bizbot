import os
import logging
from datetime import datetime
import pytz
import pandas as pd
import numpy as np
from dotenv import load_dotenv
import yfinance as yf
import json
import traceback
from telegram import Update, ParseMode, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Updater, CommandHandler, CallbackContext, CallbackQueryHandler
from flask import Flask
import threading

# Load environment variables
load_dotenv("keys.env")

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Get bot token from environment variable
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')

# Store chat IDs of subscribers and their preferences
subscribers = set()
user_watchlists = {}
user_preferences = {}

# Default symbols to scan
DEFAULT_SYMBOLS = [
    # US Large Cap Tech
    'AAPL', 'MSFT', 'AMZN', 'NVDA', 'GOOGL', 'META', 'TSLA',
    
    # US Large Cap Various Sectors
    'JPM', 'V', 'PG', 'JNJ', 'WMT', 'BAC', 'DIS', 'NFLX', 'PYPL', 'ADBE', 'CRM', 
    'COST', 'AMD', 'INTC', 'XOM', 'CVX', 'PFE', 'KO', 'MRK', 'HD', 'UNH',
    
    # ETFs
    'SPY', 'QQQ', 'DIA', 'IWM', 'VTI', 'VEA', 'VWO', 'VOO', 'VNQ',
    
    # Commodities
    'GLD', 'SLV', 'USO', 'UNG',
    
    # International
    'BABA', 'TSM', 'SONY', 'TM', 'HSBC', 'BP', 'GSK'
]

# Global variables to store opportunities
current_opportunities = []

# Helper function to format currency
def format_currency(value):
    return f"${value:.2f}"

# Get S&P 500 symbols
def get_sp500_symbols():
    """Get all S&P 500 component symbols."""
    try:
        # This uses Wikipedia's list of S&P 500 companies
        url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        tables = pd.read_html(url)
        sp500_table = tables[0]
        return sp500_table['Symbol'].tolist()
    except Exception as e:
        logger.error(f"Error getting S&P 500 symbols: {str(e)}")
        # Fallback to our predefined list if web scraping fails
        return DEFAULT_SYMBOLS

# Scan for opportunities
def scan_for_opportunities(user_id=None):
    """Scan the market for real investment opportunities based on technical analysis."""
    # Determine which symbols to scan
    symbols = []
    
    # Add user's watchlist if specified
    if user_id and user_id in user_watchlists and user_watchlists[user_id]:
        symbols.extend(user_watchlists[user_id])
    
    # If we have fewer than 50 symbols (or no user_id specified), add defaults
    if len(symbols) < 50 or user_id is None:
        # Add unique symbols from default list
        for symbol in DEFAULT_SYMBOLS:
            if symbol not in symbols:
                symbols.append(symbol)
    
    opportunities = []
    total_symbols = len(symbols)
    processed = 0
    
    for symbol in symbols:
        try:
            processed += 1
            if processed % 10 == 0:
                logger.info(f"Processing {processed}/{total_symbols} symbols...")
                
            # Get historical data
            stock = yf.Ticker(symbol)
            hist = stock.history(period="3mo")
            
            if len(hist) < 30:  # Skip if not enough data
                continue
                
            # Calculate technical indicators
            # 1. Moving Averages
            hist['SMA20'] = hist['Close'].rolling(window=20).mean()
            hist['SMA50'] = hist['Close'].rolling(window=50).mean()
            hist['SMA200'] = hist['Close'].rolling(window=200).mean()
            
            # 2. RSI (Relative Strength Index)
            delta = hist['Close'].diff()
            gain = delta.where(delta > 0, 0).rolling(window=14).mean()
            loss = -delta.where(delta < 0, 0).rolling(window=14).mean()
            rs = gain / loss
            hist['RSI'] = 100 - (100 / (1 + rs))
            
            # 3. MACD (Moving Average Convergence Divergence)
            hist['EMA12'] = hist['Close'].ewm(span=12, adjust=False).mean()
            hist['EMA26'] = hist['Close'].ewm(span=26, adjust=False).mean()
            hist['MACD'] = hist['EMA12'] - hist['EMA26']
            hist['Signal'] = hist['MACD'].ewm(span=9, adjust=False).mean()
            
            # 4. Bollinger Bands
            hist['BB_middle'] = hist['Close'].rolling(window=20).mean()
            hist['BB_std'] = hist['Close'].rolling(window=20).std()
            hist['BB_upper'] = hist['BB_middle'] + 2 * hist['BB_std']
            hist['BB_lower'] = hist['BB_middle'] - 2 * hist['BB_std']
            
            # Get the most recent data points
            current = hist.iloc[-1]
            previous = hist.iloc[-2]
            
            # Get company info
            info = stock.info
            name = info.get('shortName', symbol)
            current_price = info.get('currentPrice', current['Close'])
            if not current_price or np.isnan(current_price):
                current_price = current['Close']
            
            # Strategy 1: Golden Cross (SMA20 crosses above SMA50)
            golden_cross = previous['SMA20'] < previous['SMA50'] and current['SMA20'] > current['SMA50']
            
            # Strategy 2: RSI oversold bounce (RSI crosses above 30 from below)
            rsi_bounce = previous['RSI'] < 30 and current['RSI'] > 30
            
            # Strategy 3: MACD crosses above signal line
            macd_cross = previous['MACD'] < previous['Signal'] and current['MACD'] > current['Signal']
            
            # Strategy 4: Price bounces off lower Bollinger Band
            bb_bounce = previous['Close'] <= previous['BB_lower'] and current['Close'] > current['BB_lower']
            
            # Strategy 5: Death Cross (SMA50 crosses below SMA200)
            death_cross = previous['SMA50'] > previous['SMA200'] and current['SMA50'] < current['SMA200']
            
            # Strategy 6: RSI overbought condition (RSI above 70)
            rsi_overbought = current['RSI'] > 70
            
            # Strategy 7: MACD crosses below signal line
            macd_cross_down = previous['MACD'] > previous['Signal'] and current['MACD'] < current['Signal']
            
            # Strategy 8: Price breaks upper Bollinger Band
            bb_breakout = current['Close'] > current['BB_upper']
            
            # Determine buy/sell signal
            signal = None
            confidence = 0
            rationale = []
            
            # BUY signals
            if golden_cross:
                signal = "BUY"
                confidence += 30
                rationale.append("Golden Cross: 20-day moving average crossed above 50-day moving average")
                
            if rsi_bounce:
                signal = "BUY"
                confidence += 25
                rationale.append(f"RSI Bounce: Stock bounced from oversold condition (RSI: {current['RSI']:.1f})")
                
            if macd_cross:
                if signal != "BUY":
                    signal = "BUY"
                confidence += 25
                rationale.append("MACD Bullish: MACD line crossed above signal line")
                
            if bb_bounce:
                if signal != "BUY":
                    signal = "BUY"
                confidence += 20
                rationale.append("Bollinger Bounce: Price bounced off lower Bollinger Band")
            
            # SELL signals
            if death_cross:
                signal = "SELL"
                confidence += 30
                rationale.append("Death Cross: 50-day moving average crossed below 200-day moving average")
                
            if rsi_overbought:
                if signal != "SELL":
                    signal = "SELL"
                confidence += 25
                rationale.append(f"RSI Overbought: Stock shows overbought conditions (RSI: {current['RSI']:.1f})")
                
            if macd_cross_down:
                if signal != "SELL":
                    signal = "SELL"
                confidence += 25
                rationale.append("MACD Bearish: MACD line crossed below signal line")
                
            if bb_breakout and current['RSI'] > 65:
                if signal != "SELL":
                    signal = "SELL"
                confidence += 20
                rationale.append("Potential Top: Price above upper Bollinger Band with elevated RSI")
                
            # Additional confirmations
            if signal == "BUY":
                if current['Close'] > current['SMA20']:
                    confidence += 10
                    rationale.append("Price above 20-day moving average")
                    
                if current['SMA20'] > current['SMA50']:
                    confidence += 10
                    rationale.append("Uptrend confirmed: 20-day MA above 50-day MA")
                
                if current['Volume'] > hist['Volume'].rolling(window=20).mean().iloc[-1] * 1.5:
                    confidence += 15
                    rationale.append("Strong volume: 50% above 20-day average")
                    
            elif signal == "SELL":
                if current['Close'] < current['SMA20']:
                    confidence += 10
                    rationale.append("Price below 20-day moving average")
                    
                if current['SMA20'] < current['SMA50']:
                    confidence += 10
                    rationale.append("Downtrend confirmed: 20-day MA below 50-day MA")
                
                if current['Volume'] > hist['Volume'].rolling(window=20).mean().iloc[-1] * 1.5:
                    confidence += 15
                    rationale.append("Strong volume: 50% above 20-day average")
            
            # Only keep opportunities with confidence above 60%
            if signal and confidence >= 60:
                # Calculate target price and stop loss
                atr = hist['High'].rolling(14).max() - hist['Low'].rolling(14).min()
                avg_atr = atr.mean() / current_price  # As percentage of price
                
                if signal == "BUY":
                    # Target price: Current price + 2 * ATR
                    target_price = current_price * (1 + 2 * avg_atr)
                    # Stop loss: Current price - 1 * ATR
                    stop_loss = current_price * (1 - 1 * avg_atr)
                else:  # SELL
                    # Target price: Current price - 2 * ATR
                    target_price = current_price * (1 - 2 * avg_atr)
                    # Stop loss: Current price + 1 * ATR
                    stop_loss = current_price * (1 + 1 * avg_atr)
                
                # Calculate risk/reward ratio
                if signal == "BUY":
                    risk = current_price - stop_loss
                    reward = target_price - current_price
                else:  # SELL
                    risk = stop_loss - current_price
                    reward = current_price - target_price
                    
                risk_reward = round(reward / risk, 1) if risk > 0 else 0
                
                # Only include opportunities with good risk/reward ratio
                if risk_reward >= 1.5:
                    # Calculate units based on $100 budget
                    units = round(100 / current_price, 4)
                    potential_profit = round(units * abs(target_price - current_price), 2)
                    max_loss = round(units * abs(current_price - stop_loss), 2)
                    
                    opportunities.append({
                        "type": "Stock",
                        "symbol": symbol,
                        "name": name,
                        "signal": signal,
                        "price": round(current_price, 2),
                        "target_price": round(target_price, 2),
                        "stop_loss": round(stop_loss, 2),
                        "risk_reward": risk_reward,
                        "confidence": confidence,
                        "units": units,
                        "potential_profit": potential_profit,
                        "max_loss": max_loss,
                        "rationale": ". ".join(rationale),
                        "indicators": {
                            "rsi": round(current['RSI'], 2),
                            "macd": round(current['MACD'], 4),
                            "signal": round(current['Signal'], 4)
                        }
                    })
                
        except Exception as e:
            logger.error(f"Error analyzing {symbol}: {str(e)}")
            continue
    
    # Sort opportunities by confidence and then by risk/reward ratio
    opportunities.sort(key=lambda x: (x['confidence'], x['risk_reward']), reverse=True)
    
    # Keep top 10 opportunities
    return opportunities[:10]

# Function to update opportunities
def update_opportunities(user_id=None):
    global current_opportunities
    
    if user_id:
        # Scan for specific user's watchlist
        return scan_for_opportunities(user_id)
    else:
        # Update global opportunities
        current_opportunities = scan_for_opportunities()
        return current_opportunities

# Send an opportunity alert
def send_opportunity_alert(context: CallbackContext, opportunity, chat_id=None):
    """Send an opportunity alert for a specific opportunity."""
    op = opportunity
    
    # Format the message with more detailed analysis
    message = (
        f"📊 *OPPORTUNITY ALERT* 📊\n\n"
        f"*{op['symbol']}: {op['name']}*\n"
        f"*Signal:* {op['signal']}\n"
        f"*Current Price:* {format_currency(op['price'])}\n"
        f"*Target Price:* {format_currency(op['target_price'])}\n"
        f"*Stop Loss:* {format_currency(op['stop_loss'])}\n\n"
        f"*Analysis:*\n"
        f"• Risk/Reward: {op['risk_reward']} (Higher is better)\n"
        f"• Confidence: {op['confidence']}%\n"
        f"• RSI: {op['indicators']['rsi']}\n"
        f"• MACD: {op['indicators']['macd']}\n\n"
        f"*Your $100 Investment:*\n"
        f"• Units to buy: {op['units']}\n"
        f"• Potential profit: {format_currency(op['potential_profit'])}\n"
        f"• Maximum loss: {format_currency(op['max_loss'])}\n\n"
        f"*Rationale:*\n{op['rationale']}"
    )
    
    # Create buttons for easy actions
    keyboard = [
        [
            InlineKeyboardButton("Add to Watchlist", callback_data=f"add_{op['symbol']}"),
            InlineKeyboardButton("More Details", callback_data=f"more_{op['symbol']}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if chat_id:
        context.bot.send_message(
            chat_id=chat_id, 
            text=message, 
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
    else:
        for subscriber in subscribers:
            context.bot.send_message(
                chat_id=subscriber, 
                text=message, 
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=reply_markup
            )

# Command handlers
def start(update: Update, context: CallbackContext) -> None:
    """Send a welcome message when the command /start is issued."""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    subscribers.add(chat_id)
    
    message = (
        f"🤖 *Financial Opportunity Scout* 🤖\n\n"
        f"Welcome to your personal investment alert system!\n\n"
        f"I'll scan the markets and notify you of potential opportunities based on "
        f"technical and fundamental analysis.\n\n"
        f"Each opportunity will be tailored to your $100 weekly investment budget.\n\n"
        f"*Available Commands:*\n"
        f"/scan - Run a market scan now\n"
        f"/watchlist - See current opportunities\n"
        f"/add [symbol] - Add a symbol to your watchlist\n"
        f"/search [name] - Search for any tradable symbol\n"
        f"/help - Show all commands"
    )
    
    update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

def help_command(update: Update, context: CallbackContext) -> None:
    """Send a help message when the command /help is issued."""
    message = (
        f"*Available Commands:*\n\n"
        f"/scan - Run a market scan immediately\n"
        f"/watchlist - View current opportunities\n"
        f"/details [symbol] - Get detailed analysis on a specific asset\n"
        f"/add [symbol] - Add a symbol to your watchlist\n"
        f"/remove [symbol] - Remove a symbol from your watchlist\n"
        f"/mylist - View your personal watchlist\n"
        f"/search [name] - Search for any tradable symbol\n"
        f"/settings - Configure your alert preferences\n"
        f"/help - Show this help message"
    )
    
    update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

def scan_command(update: Update, context: CallbackContext) -> None:
    """Run a market scan when the command /scan is issued."""
    update.message.reply_text("🔍 Scanning markets for opportunities...\nThis may take a minute for a thorough analysis.")
    
    user_id = update.effective_user.id
    
    # Update opportunities for this user
    user_opps = update_opportunities(user_id)
    
    if user_opps:
        update.message.reply_text(f"Found {len(user_opps)} investment opportunities!")
        # Send the top opportunity
        send_opportunity_alert(context, user_opps[0], update.effective_chat.id)
        
        if len(user_opps) > 1:
            update.message.reply_text("Use /watchlist to see all opportunities.")
    else:
        update.message.reply_text("No clear investment opportunities found at this time. Try again later or add more symbols to your watchlist with /add [symbol].")

def watchlist_command(update: Update, context: CallbackContext) -> None:
    """Show current opportunities when the command /watchlist is issued."""
    global current_opportunities
    user_id = update.effective_user.id
    
    # Use user-specific opportunities if available, otherwise fall back to global
    opportunities = update_opportunities(user_id) if user_id else current_opportunities
    
    if not opportunities:
        opportunities = update_opportunities()
    
    if not opportunities:
        update.message.reply_text("No opportunities found. Use /scan to search for new opportunities.")
        return
    
    # Format the watchlist message
    message = "*Current Investment Opportunities:*\n\n"
    
    for i, op in enumerate(opportunities, 1):
        message += f"{i}. {op['symbol']} ({op['name']}) - {op['signal']} at {format_currency(op['price'])}\n"
        message += f"   Risk/Reward: {op['risk_reward']} | Confidence: {op['confidence']}%\n"
    
    message += "\nUse /details [symbol] for more information on any opportunity."
    
    # Create buttons for easy navigation
    keyboard = []
    row = []
    for i, op in enumerate(opportunities[:5], 1):
        row.append(InlineKeyboardButton(f"{i}. {op['symbol']}", callback_data=f"details_{op['symbol']}"))
        if len(row) == 3:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

def details_command(update: Update, context: CallbackContext) -> None:
    """Show details for a specific symbol."""
    global current_opportunities
    
    if not context.args:
        update.message.reply_text("Please provide a symbol. Example: /details AAPL")
        return
    
    symbol = context.args[0].upper()
    user_id = update.effective_user.id
    
    # Check for the symbol in either user-specific or global opportunities
    user_opps = update_opportunities(user_id) if user_id else []
    matching_opportunities = [op for op in user_opps if op['symbol'] == symbol]
    
    if not matching_opportunities:
        matching_opportunities = [op for op in current_opportunities if op['symbol'] == symbol]
    
    if matching_opportunities:
        # Send details for this opportunity
        send_opportunity_alert(context, matching_opportunities[0], update.effective_chat.id)
    else:
        # Try to analyze the symbol now
        try:
            update.message.reply_text(f"Analyzing {symbol}... This will take a moment.")
            
            # Get ticker data
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="3mo")
            
            if len(hist) < 30:
                update.message.reply_text(f"Not enough historical data for {symbol} to perform analysis.")
                return
                
            # Calculate basic indicators
            hist['SMA20'] = hist['Close'].rolling(window=20).mean()
            hist['SMA50'] = hist['Close'].rolling(window=50).mean()
            
            delta = hist['Close'].diff()
            gain = delta.where(delta > 0, 0).rolling(window=14).mean()
            loss = -delta.where(delta < 0, 0).rolling(window=14).mean()
            rs = gain / loss
            hist['RSI'] = 100 - (100 / (1 + rs))
            
            # Get latest data
            current = hist.iloc[-1]
            info = ticker.info
            name = info.get('shortName', symbol)
            current_price = info.get('currentPrice', current['Close'])
            if not current_price or np.isnan(current_price):
                current_price = current['Close']
            
            previous_close = info.get('previousClose', hist.iloc[-2]['Close'])
            
            change = current_price - previous_close
            change_percent = (change / previous_close) * 100 if previous_close else 0
            
            # Basic analysis
            sma20 = current['SMA20']
            sma50 = current['SMA50']
            rsi = current['RSI']
            
            trend = "Bullish" if sma20 > sma50 else "Bearish"
            rsi_status = "Overbought" if rsi > 70 else "Oversold" if rsi < 30 else "Neutral"
            
            message = (
                f"*{symbol}: {name}*\n\n"
                f"Current Price: {format_currency(current_price)}\n"
                f"Previous Close: {format_currency(previous_close)}\n"
                f"Change: {format_currency(change)} ({change_percent:.2f}%)\n\n"
                f"*Technical Analysis:*\n"
                f"• Trend: {trend}\n"
                f"• RSI: {rsi:.2f} ({rsi_status})\n"
                f"• 20-day MA: {sma20:.2f}\n"
                f"• 50-day MA: {sma50:.2f}\n\n"
                f"No specific trading opportunity identified yet.\n"
                f"Run /scan to find new opportunities or add to your watchlist with /add {symbol}"
            )
            
            # Create buttons for easy actions
            keyboard = [
                [
                    InlineKeyboardButton("Add to Watchlist", callback_data=f"add_{symbol}"),
                    InlineKeyboardButton("Full Analysis", callback_data=f"analyze_{symbol}")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"Error in details: {str(e)}")
            update.message.reply_text(f"Could not analyze {symbol}. Please check if the symbol is valid.")

def add_to_watchlist_command(update: Update, context: CallbackContext) -> None:
    """Add a symbol to user's watchlist."""
    if not context.args:
        update.message.reply_text("Please provide a symbol. Example: /add AAPL")
        return
    
    symbol = context.args[0].upper()
    user_id = update.effective_user.id
    
    # Initialize user's watchlist if it doesn't exist
    if user_id not in user_watchlists:
        user_watchlists[user_id] = []
    
    # Check if symbol is valid
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info
        name = info.get('shortName', 'Unknown')
        
        # Add to watchlist if valid
        if symbol not in user_watchlists[user_id]:
            user_watchlists[user_id].append(symbol)
            update.message.reply_text(f"Added {symbol} ({name}) to your watchlist. Use /mylist to see your full watchlist.")
        else:
            update.message.reply_text(f"{symbol} is already in your watchlist.")
    except:
        update.message.reply_text(f"Could not find symbol {symbol}. Please check the symbol and try again.")

def remove_from_watchlist_command(update: Update, context: CallbackContext) -> None:
    """Remove a symbol from user's watchlist."""
    if not context.args:
        update.message.reply_text("Please provide a symbol. Example: /remove AAPL")
        return
    
    symbol = context.args[0].upper()
    user_id = update.effective_user.id
    
    if user_id in user_watchlists and symbol in user_watchlists[user_id]:
        user_watchlists[user_id].remove(symbol)
        update.message.reply_text(f"Removed {symbol} from your watchlist.")
    else:
        update.message.reply_text(f"{symbol} is not in your watchlist.")

def mylist_command(update: Update, context: CallbackContext) -> None:
    """Show user's personal watchlist."""
    user_id = update.effective_user.id
    
    if user_id not in user_watchlists or not user_watchlists[user_id]:
        update.message.reply_text("Your watchlist is empty. Add symbols with /add [symbol]")
        return
    
    # Get current prices for watchlist symbols
    message = "*Your Watchlist:*\n\n"
    
    for symbol in user_watchlists[user_id]:
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            name = info.get('shortName', symbol)
            price = info.get('currentPrice', 0)
            if not price or np.isnan(price):
                price = ticker.history(period="1d").iloc[0]['Close']
                
            message += f"• {symbol} ({name}): {format_currency(price)}\n"
        except:
            message += f"• {symbol}: Price unavailable\n"
    
    message += "\nUse /details [symbol] for more information on any symbol."
    message += "\nUse /remove [symbol] to remove a symbol from your watchlist."
    
    update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

def search_symbol_command(update: Update, context: CallbackContext) -> None:
    """Search for any tradable symbol."""
    if not context.args:
        update.message.reply_text("Please provide a search term. Example: /search apple")
        return
    
    search_term = ' '.join(context.args)
    update.message.reply_text(f"Searching for '{search_term}'...")
    
    try:
        # Use Yahoo Finance search API through pandas datareader
        symbols = []
        
        # Try direct lookup first
        try:
            ticker = yf.Ticker(search_term.upper())
            info = ticker.info
            if 'symbol' in info:
                symbols.append({
                    'symbol': info['symbol'],
                    'name': info.get('shortName', 'Unknown'),
                    'exchange': info.get('exchange', 'Unknown')
                })
        except:
            pass
        
        # Common US exchanges
        exchanges = ['NASDAQ', 'NYSE', 'AMEX']
        
        # Try searching with exchange suffixes
        for exchange in exchanges:
            try:
                ticker = yf.Ticker(f"{search_term.upper()}.{exchange}")
                info = ticker.info
                if 'symbol' in info:
                    symbols.append({
                        'symbol': info['symbol'],
                        'name': info.get('shortName', 'Unknown'),
                        'exchange': info.get('exchange', 'Unknown')
                    })
            except:
                continue
        
        # If nothing found by direct lookup, try related symbols
        if not symbols:
            # Basic keyword search simulation (this is a simplified approach)
            candidates = DEFAULT_SYMBOLS
            
            for symbol in candidates:
                try:
                    ticker = yf.Ticker(symbol)
                    info = ticker.info
                    name = info.get('shortName', 'Unknown').lower()
                    
                    if search_term.lower() in name.lower() or search_term.lower() in symbol.lower():
                        symbols.append({
                            'symbol': symbol,
                            'name': info.get('shortName', 'Unknown'),
                            'exchange': info.get('exchange', 'Unknown')
                        })
                        
                        # Limit to 10 results
                        if len(symbols) >= 10:
                            break
                except:
                    continue
            
        if symbols:
            message = "*Search Results:*\n\n"
            
            for result in symbols:
             message += f"{result['symbol']}: {result['name']} ({result['exchange']})\n"                
             message += "\nUse /details [symbol] to see details for any of these symbols."
             message += "\nUse /add [symbol] to add a symbol to your watchlist."
            
            # Create buttons for quick access to top 5 results
            keyboard = []
            row = []
            for i, result in enumerate(symbols[:5]):
                symbol = result['symbol']
                row.append(InlineKeyboardButton(symbol, callback_data=f"details_{symbol}"))
                if len(row) == 3 or i == len(symbols[:5]) - 1:
                    keyboard.append(row)
                    row = []
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
        else:
            update.message.reply_text(f"No results found for '{search_term}'. Try a different search term.")
    except Exception as e:
        logger.error(f"Search error: {str(e)}\n{traceback.format_exc()}")
        update.message.reply_text(f"Error searching for '{search_term}'. Please try a different search term.")

def settings_command(update: Update, context: CallbackContext) -> None:
    """Configure user settings."""
    user_id = update.effective_user.id
    
    # Initialize user preferences if not exist
    if user_id not in user_preferences:
        user_preferences[user_id] = {
            "daily_alerts": True,
            "min_confidence": 60,
            "min_risk_reward": 1.5
        }
    
    prefs = user_preferences[user_id]
    
    message = (
        "*Your Settings:*\n\n"
        f"• Daily Alerts: {'Enabled' if prefs['daily_alerts'] else 'Disabled'}\n"
        f"• Minimum Confidence: {prefs['min_confidence']}%\n"
        f"• Minimum Risk/Reward: {prefs['min_risk_reward']}\n\n"
        "Use the buttons below to change your settings:"
    )
    
    keyboard = [
        [
            InlineKeyboardButton(
                f"{'Disable' if prefs['daily_alerts'] else 'Enable'} Alerts", 
                callback_data="toggle_alerts"
            )
        ],
        [
            InlineKeyboardButton("Min Confidence: 60%", callback_data="conf_60"),
            InlineKeyboardButton("Min Confidence: 70%", callback_data="conf_70"),
            InlineKeyboardButton("Min Confidence: 80%", callback_data="conf_80")
        ],
        [
            InlineKeyboardButton("Risk/Reward: 1.5", callback_data="rr_1.5"),
            InlineKeyboardButton("Risk/Reward: 2.0", callback_data="rr_2.0"),
            InlineKeyboardButton("Risk/Reward: 2.5", callback_data="rr_2.5")
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

def button_callback(update: Update, context: CallbackContext) -> None:
    """Handle button presses."""
    query = update.callback_query
    query.answer()
    
    data = query.data
    user_id = update.effective_user.id
    
    if data.startswith("details_"):
        # Handle details button
        symbol = data[8:]
        
        # Simulate the details command
        context.args = [symbol]
        details_command(update, context)
        
    elif data.startswith("add_"):
        # Handle add to watchlist button
        symbol = data[4:]
        
        # Initialize user's watchlist if it doesn't exist
        if user_id not in user_watchlists:
            user_watchlists[user_id] = []
        
        # Check if symbol is valid and add to watchlist
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            name = info.get('shortName', 'Unknown')
            
            if symbol not in user_watchlists[user_id]:
                user_watchlists[user_id].append(symbol)
                query.edit_message_text(f"Added {symbol} ({name}) to your watchlist. Use /mylist to see your full watchlist.")
            else:
                query.edit_message_text(f"{symbol} is already in your watchlist.")
        except:
            query.edit_message_text(f"Could not add {symbol} to your watchlist. Please try again.")
    
    elif data.startswith("analyze_"):
        # Handle full analysis button
        symbol = data[8:]
        
        # Run a deeper analysis for this symbol only
        query.edit_message_text(f"Running full analysis for {symbol}... This will take a moment.")
        
        try:
            # Simulate scanning just this one symbol
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="6mo")
            
            if len(hist) < 30:
                query.edit_message_text(f"Not enough historical data for {symbol} to perform analysis.")
                return
            
            # Calculate all indicators (same as in scan_for_opportunities)
            # (This is simplified - in a real bot, you'd reuse the analysis code)
            hist['SMA20'] = hist['Close'].rolling(window=20).mean()
            hist['SMA50'] = hist['Close'].rolling(window=50).mean()
            hist['SMA200'] = hist['Close'].rolling(window=200).mean()
            
            delta = hist['Close'].diff()
            gain = delta.where(delta > 0, 0).rolling(window=14).mean()
            loss = -delta.where(delta < 0, 0).rolling(window=14).mean()
            rs = gain / loss
            hist['RSI'] = 100 - (100 / (1 + rs))
            
            hist['EMA12'] = hist['Close'].ewm(span=12, adjust=False).mean()
            hist['EMA26'] = hist['Close'].ewm(span=26, adjust=False).mean()
            hist['MACD'] = hist['EMA12'] - hist['EMA26']
            hist['Signal'] = hist['MACD'].ewm(span=9, adjust=False).mean()
            
            # Get latest price and info
            current = hist.iloc[-1]
            info = ticker.info
            name = info.get('shortName', symbol)
            current_price = info.get('currentPrice', current['Close'])
            
            # Create detailed analysis
            message = (
                f"*Detailed Analysis for {symbol} ({name})*\n\n"
                f"Current Price: {format_currency(current_price)}\n\n"
                f"*Technical Indicators:*\n"
                f"• 20-day MA: {current['SMA20']:.2f}\n"
                f"• 50-day MA: {current['SMA50']:.2f}\n"
                f"• 200-day MA: {current['SMA200']:.2f}\n"
                f"• RSI (14): {current['RSI']:.2f}\n"
                f"• MACD: {current['MACD']:.4f}\n"
                f"• Signal Line: {current['Signal']:.4f}\n\n"
            )
            
            # Add analysis conclusions
            trend_longterm = "Bullish" if current['SMA50'] > current['SMA200'] else "Bearish"
            trend_shortterm = "Bullish" if current['SMA20'] > current['SMA50'] else "Bearish"
            
            rsi_status = "Overbought" if current['RSI'] > 70 else "Oversold" if current['RSI'] < 30 else "Neutral"
            
            macd_signal = "Bullish" if current['MACD'] > current['Signal'] else "Bearish"
            
            message += (
                f"*Analysis:*\n"
                f"• Long-term Trend: {trend_longterm}\n"
                f"• Short-term Trend: {trend_shortterm}\n"
                f"• RSI Status: {rsi_status}\n"
                f"• MACD Signal: {macd_signal}\n\n"
            )
            
            # Add recommendation
            if trend_longterm == "Bullish" and trend_shortterm == "Bullish" and current['RSI'] < 70 and macd_signal == "Bullish":
                recommendation = "STRONG BUY"
            elif trend_shortterm == "Bullish" and macd_signal == "Bullish":
                recommendation = "BUY"
            elif trend_longterm == "Bearish" and trend_shortterm == "Bearish" and current['RSI'] > 30 and macd_signal == "Bearish":
                recommendation = "STRONG SELL"
            elif trend_shortterm == "Bearish" and macd_signal == "Bearish":
                recommendation = "SELL"
            else:
                recommendation = "HOLD"
            
            message += f"*Recommendation:* {recommendation}\n\n"
            
            # Add performance metrics
            try:
                one_month_change = (hist.iloc[-1]['Close'] / hist.iloc[-21]['Close'] - 1) * 100
                three_month_change = (hist.iloc[-1]['Close'] / hist.iloc[-63]['Close'] - 1) * 100
                
                message += (
                    f"*Performance:*\n"
                    f"• 1-Month Change: {one_month_change:.2f}%\n"
                    f"• 3-Month Change: {three_month_change:.2f}%\n\n"
                )
                
                message += "Use /add to add this symbol to your watchlist."
            except:
                message += "Historical performance data not available."
            
            query.edit_message_text(message, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            query.edit_message_text(f"Error analyzing {symbol}: {str(e)}")
    
    elif data == "toggle_alerts":
        # Toggle daily alerts setting
        if user_id not in user_preferences:
            user_preferences[user_id] = {
                "daily_alerts": True,
                "min_confidence": 60,
                "min_risk_reward": 1.5
            }
        
        user_preferences[user_id]["daily_alerts"] = not user_preferences[user_id]["daily_alerts"]
        
        # Recreate the settings message and buttons
        settings_command(update, context)
    
    elif data.startswith("conf_"):
        # Change confidence setting
        conf_value = int(data[5:])
        
        if user_id not in user_preferences:
            user_preferences[user_id] = {
                "daily_alerts": True,
                "min_confidence": 60,
                "min_risk_reward": 1.5
            }
        
        user_preferences[user_id]["min_confidence"] = conf_value
        
        # Recreate the settings message and buttons
        settings_command(update, context)
    
    elif data.startswith("rr_"):
        # Change risk/reward setting
        rr_value = float(data[3:])
        
        if user_id not in user_preferences:
            user_preferences[user_id] = {
                "daily_alerts": True,
                "min_confidence": 60,
                "min_risk_reward": 1.5
            }
        
        user_preferences[user_id]["min_risk_reward"] = rr_value
        
        # Recreate the settings message and buttons
        settings_command(update, context)

def broadcast_opportunities(context: CallbackContext) -> None:
    """Send the top opportunity to all subscribers."""
    global current_opportunities
    
    # Update global opportunities
    opportunities = update_opportunities()
    
    if opportunities and subscribers:
        for subscriber in subscribers:
            user_id = subscriber
            
            # Check user preferences
            min_confidence = 60
            if user_id in user_preferences:
                if not user_preferences[user_id].get("daily_alerts", True):
                    continue  # Skip this user if they've disabled alerts
                min_confidence = user_preferences[user_id].get("min_confidence", 60)
            
            # Filter opportunities by user's minimum confidence
            user_opps = [op for op in opportunities if op['confidence'] >= min_confidence]
            
            if user_opps:
                context.bot.send_message(
                    chat_id=subscriber,
                    text="📊 *Market Scan Update* 📊\nHere's today's top investment opportunity:",
                    parse_mode=ParseMode.MARKDOWN
                )
                send_opportunity_alert(context, user_opps[0], subscriber)
                
                if len(user_opps) > 1:
                    context.bot.send_message(
                        chat_id=subscriber,
                        text="Use /watchlist to see all current opportunities.",
                        parse_mode=ParseMode.MARKDOWN
                    )

def schedule_scans(context: CallbackContext) -> None:
    """Function to schedule regular market scans."""
    job_queue = context.job_queue
    
    # Initial scan at startup
    update_opportunities()
    
    # Schedule pre-market scan (9:30 AM ET on weekdays)
    job_queue.run_daily(
        lambda ctx: broadcast_opportunities(ctx),
        time=datetime.strptime('09:30', '%H:%M').time(),
        days=(0, 1, 2, 3, 4),  # Monday to Friday
        context=context,
        name='pre_market_scan'
    )
    
    # Schedule post-market scan (4:00 PM ET on weekdays)
    job_queue.run_daily(
        lambda ctx: broadcast_opportunities(ctx),
        time=datetime.strptime('16:00', '%H:%M').time(),
        days=(0, 1, 2, 3, 4),  # Monday to Friday
        context=context,
        name='post_market_scan'
    )
    
    # Refresh opportunities every 4 hours
    job_queue.run_repeating(
        lambda ctx: update_opportunities(),
        interval=14400,  # 4 hours in seconds
        first=7200,      # First run after 2 hours
        context=context,
        name='refresh_opportunities'
    )

# Create a Flask app for keeping the bot alive
app = Flask(__name__)

@app.route('/')
def index():
    return "Bot is alive!"

def run_flask():
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))

def main() -> None:
    """Start the bot."""
    # Create the Updater and pass it your bot's token
    updater = Updater(TOKEN)
    
    # Get the dispatcher to register handlers
    dispatcher = updater.dispatcher
    
    # Register command handlers
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("help", help_command))
    dispatcher.add_handler(CommandHandler("scan", scan_command))
    dispatcher.add_handler(CommandHandler("watchlist", watchlist_command))
    dispatcher.add_handler(CommandHandler("details", details_command))
    dispatcher.add_handler(CommandHandler("add", add_to_watchlist_command))
    dispatcher.add_handler(CommandHandler("remove", remove_from_watchlist_command))
    dispatcher.add_handler(CommandHandler("mylist", mylist_command))
    dispatcher.add_handler(CommandHandler("search", search_symbol_command))
    dispatcher.add_handler(CommandHandler("settings", settings_command))
    
    # Register callback query handler
    dispatcher.add_handler(CallbackQueryHandler(button_callback))
    
    # Schedule regular market scans
    schedule_scans(updater)
    
    # Start the Flask server in a separate thread
    threading.Thread(target=run_flask, daemon=True).start()
    
    # Start the Bot
    updater.start_polling()
    
    # Run the bot until you press Ctrl-C
    updater.idle()

if __name__ == '__main__':
    main()