import os
import logging
from datetime import datetime
import pytz
import pandas as pd
from dotenv import load_dotenv
import yfinance as yf
from telegram import Update, ParseMode
from telegram.ext import Updater, CommandHandler, CallbackContext

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

# Store chat IDs of subscribers
subscribers = set()

# Helper function to format currency
def format_currency(value):
    return f"${value:.2f}"

# Send an opportunity alert
def send_opportunity_alert(context: CallbackContext, chat_id=None):
    # In a real implementation, this would analyze market data
    # For demonstration, we'll use mock data
    
    # Mock opportunity
    opportunity = {
        "type": "Stock",
        "symbol": "AAPL",
        "name": "Apple Inc.",
        "signal": "BUY",
        "price": 202.75,
        "target_price": 235.00,
        "stop_loss": 190.00,
        "risk_reward": 2.3,
        "confidence": 85,
        "units": round(100 / 202.75, 2),  # $100 budget
        "potential_profit": round((235.00 - 202.75) * (100 / 202.75), 2),
        "max_loss": round((202.75 - 190.00) * (100 / 202.75), 2),
        "rationale": "Strong earnings beat, positive guidance, and technical breakout from consolidation pattern"
    }
    
    # Format the message
    message = (
        f"📊 *OPPORTUNITY ALERT* 📊\n\n"
        f"*Symbol:* {opportunity['symbol']}\n"
        f"*Company:* {opportunity['name']}\n"
        f"*Signal:* {opportunity['signal']}\n"
        f"*Current Price:* {format_currency(opportunity['price'])}\n"
        f"*Target Price:* {format_currency(opportunity['target_price'])}\n"
        f"*Stop Loss:* {format_currency(opportunity['stop_loss'])}\n\n"
        f"*Risk/Reward:* {opportunity['risk_reward']}\n"
        f"*Confidence:* {opportunity['confidence']}%\n\n"
        f"*Your $100 budget:*\n"
        f"Units to buy: {opportunity['units']}\n"
        f"Potential profit: {format_currency(opportunity['potential_profit'])}\n"
        f"Maximum loss: {format_currency(opportunity['max_loss'])}\n\n"
        f"*Rationale:*\n{opportunity['rationale']}"
    )
    
    # Send to specific chat_id or all subscribers
    if chat_id:
        context.bot.send_message(chat_id=chat_id, text=message, parse_mode=ParseMode.MARKDOWN)
    else:
        for subscriber in subscribers:
            context.bot.send_message(chat_id=subscriber, text=message, parse_mode=ParseMode.MARKDOWN)

# Command handlers
def start(update: Update, context: CallbackContext) -> None:
    """Send a welcome message when the command /start is issued."""
    chat_id = update.effective_chat.id
    subscribers.add(chat_id)
    
    message = (
        f"🤖 *Financial Opportunity Scout* 🤖\n\n"
        f"Welcome to your personal investment alert system!\n\n"
        f"I'll scan the markets and notify you of potential opportunities based on "
        f"technical and fundamental analysis.\n\n"
        f"Each opportunity will be tailored to your $100 weekly investment budget.\n\n"
        f"Commands:\n"
        f"/scan - Run a market scan now\n"
        f"/watchlist - See current opportunities\n"
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
        f"/settings - Configure your alert preferences\n"
        f"/performance - Track past recommendations\n"
        f"/help - Show this help message"
    )
    
    update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

def scan_command(update: Update, context: CallbackContext) -> None:
    """Run a market scan when the command /scan is issued."""
    update.message.reply_text("🔍 Scanning markets for opportunities...")
    
    # This would typically involve analyzing market data
    # For now, we'll just send a mock opportunity
    send_opportunity_alert(context, update.effective_chat.id)

def watchlist_command(update: Update, context: CallbackContext) -> None:
    """Show current opportunities when the command /watchlist is issued."""
    # In a full implementation, this would show actual opportunities
    # For now, we'll just send a placeholder message
    message = (
        "*Current Watchlist:*\n\n"
        "1. AAPL (Apple Inc.) - BUY at $202.75\n"
        "2. GC (Gold Futures) - BUY at $2,685.40\n"
        "3. VNQ (Vanguard Real Estate ETF) - SELL at $83.25\n\n"
        "Use /details [symbol] for more information on any opportunity."
    )
    
    update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

def details_command(update: Update, context: CallbackContext) -> None:
    """Show details for a specific symbol."""
    if not context.args:
        update.message.reply_text("Please provide a symbol. Example: /details AAPL")
        return
    
    symbol = context.args[0].upper()
    
    # In a full implementation, fetch actual data for the symbol
    # For now, we'll simulate this with conditionals
    if symbol == "AAPL":
        send_opportunity_alert(context, update.effective_chat.id)
    else:
        # Try to get real data for the symbol
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            
            # Basic info that should be available for most symbols
            name = info.get('shortName', 'Unknown')
            current_price = info.get('currentPrice', 0)
            previous_close = info.get('previousClose', 0)
            
            change = current_price - previous_close
            change_percent = (change / previous_close) * 100 if previous_close else 0
            
            message = (
                f"*{symbol}: {name}*\n\n"
                f"Current Price: {format_currency(current_price)}\n"
                f"Previous Close: {format_currency(previous_close)}\n"
                f"Change: {format_currency(change)} ({change_percent:.2f}%)\n\n"
                f"No specific opportunity identified for this symbol yet.\n"
                f"Run /scan to check for new opportunities."
            )
            
            update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
            
        except Exception as e:
            update.message.reply_text(f"Could not find data for symbol {symbol}. Please check the symbol and try again.")

def schedule_scans(context: CallbackContext) -> None:
    """Function to schedule regular market scans."""
    job_queue = context.job_queue
    
    # Schedule pre-market scan (9:30 AM ET on weekdays)
    job_queue.run_daily(
        lambda ctx: send_opportunity_alert(ctx),
        time=datetime.strptime('09:30', '%H:%M').time(),
        days=(0, 1, 2, 3, 4),  # Monday to Friday
        context=context,
        name='pre_market_scan'
    )
    
    # Schedule post-market scan (4:00 PM ET on weekdays)
    job_queue.run_daily(
        lambda ctx: send_opportunity_alert(ctx),
        time=datetime.strptime('16:00', '%H:%M').time(),
        days=(0, 1, 2, 3, 4),  # Monday to Friday
        context=context,
        name='post_market_scan'
    )

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
    
    # Schedule regular market scans
    schedule_scans(updater)
    
    # Start the Bot
    updater.start_polling()
    
    # Run the bot until you press Ctrl-C
    updater.idle()

if __name__ == '__main__':
    main()