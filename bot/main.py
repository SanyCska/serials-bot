import os
import logging

from telegram import Update, ParseMode, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Updater,
    CommandHandler,
    MessageHandler,
    Filters,
    CallbackQueryHandler,
    ConversationHandler,
    CallbackContext,
)
from dotenv import load_dotenv
from flask import Flask
import threading

from bot.database.db_handler import DBHandler
from bot.tmdb_api import TMDBApi
from bot.scheduler import NotificationScheduler
from bot.conversations import (
    ConversationManager,
    SELECTING_SERIES,
    CANCEL_PATTERN,
    SERIES_SELECTION,
    SERIES_PATTERN,
)
from bot.watch_later_handlers import WatchLaterHandlers
from bot.watchlist_handlers import WatchlistHandlers
from bot.watched_handlers import WatchedHandlers

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Create Flask app for health check
app = Flask(__name__)

@app.route('/')
def health_check():
    return 'Bot is running'

class SeriesTrackerBot:
    def __init__(self, token, db, tmdb, webhook_url=None, port=8443):
        """Initialize the bot with the given token and database handler."""
        self.updater = Updater(token)
        self.dispatcher = self.updater.dispatcher
        self.db = db
        self.tmdb = tmdb
        self.webhook_url = webhook_url
        self.port = port
        self.conversation_manager = ConversationManager(db, tmdb)
        self.watchlist_handlers = WatchlistHandlers(db, tmdb)
        self.watched_handlers = WatchedHandlers(db, tmdb)
        self.watch_later_handlers = WatchLaterHandlers(db, tmdb)
        
        # Set up the Telegram bot with higher timeout
        request_kwargs = {
            'read_timeout': 30,
            'connect_timeout': 30
        }
        self.updater = Updater(token=os.getenv('TELEGRAM_BOT_TOKEN'), use_context=True, request_kwargs=request_kwargs)
        self.dispatcher = self.updater.dispatcher
        
        # Create notification scheduler
        self.scheduler = NotificationScheduler(self.updater.bot)
        
        # Set up bot commands for command menu
        self._set_commands()
        
        # Register handlers
        self.setup_handlers()
        
    def _set_commands(self):
        """Set the commands menu for the bot"""
        bot_commands = [
            ('start', 'Запустить бота'),
            ('help', 'Показать справку'),
            ('addinwatchlist', "Добавить новый сериал для отслеживания"),
            ('watchlist', 'Сериалы в процессе просмотра'),
            ('watchlater', 'Сериалы, которые планируете посмотреть'),
            ('addinwatchlater', 'Добавить сериал в список "Посмотреть позже"'),
            ('watched', 'Список всех просмотренных сериалов'),
            # ('addwatched', 'Add a new watched series'),
        ]
        
        self.updater.bot.set_my_commands(bot_commands)
        logger.info("Bot commands menu set up successfully")
        
    def setup_handlers(self):
        """Set up all the handlers for the bot."""
        # Command handlers
        self.dispatcher.add_handler(CommandHandler("start", self.start))
        self.dispatcher.add_handler(CommandHandler("help", self.help_command))
        self.dispatcher.add_handler(CommandHandler("watchlist", self.list_series))
        self.dispatcher.add_handler(CommandHandler("watchlater", self.watch_later_handlers.view_watch_later_start))
        # Note: addinwatchlater is handled by the ConversationHandler below
        self.dispatcher.add_handler(CommandHandler("addwatched", self.watched_handlers.add_watched_series_start))
        self.dispatcher.add_handler(CommandHandler("watched", self.watched_handlers.list_watched))

        # Add series in watchlist conversation handler
        add_series_conv = self.watchlist_handlers.get_add_series_conversation_handler(self.conversation_manager)
        
        # Add the conversation handler to dispatcher
        self.dispatcher.add_handler(add_series_conv)
        
        # Update progress conversation handler
        update_progress_conv = self.watchlist_handlers.get_update_progress_conversation_handler(self.conversation_manager)
        self.dispatcher.add_handler(update_progress_conv)
        
        # Add watched series conversation handler (must be before generic handlers)
        add_watched_conv = self.watched_handlers.get_add_watched_conversation_handler(self.conversation_manager)
        self.dispatcher.add_handler(add_watched_conv)
        
        # Add watch later conversation handler
        add_watchlater_conv = ConversationHandler(
            entry_points=[
                CommandHandler("addinwatchlater", self.watch_later_handlers.add_to_watch_later_start),
                CallbackQueryHandler(self.watch_later_handlers.add_to_watch_later_start, pattern="^command_addwatch$")
            ],
            states={
                SELECTING_SERIES: [
                    MessageHandler(Filters.text & ~Filters.command, self.conversation_manager.search_series),
                    CallbackQueryHandler(self.watch_later_handlers.watchlater_series_selected, pattern=f"^{SERIES_PATTERN.format('.*')}$"),
                    CallbackQueryHandler(self.conversation_manager.cancel, pattern=f"^{CANCEL_PATTERN}$"),
                    CommandHandler("cancel", self.conversation_manager.cancel)
                ],
                SERIES_SELECTION: [
                    CallbackQueryHandler(self.watch_later_handlers.watchlater_series_selected, pattern=f"^{SERIES_PATTERN.format('.*')}$"),
                    CallbackQueryHandler(self.conversation_manager.cancel, pattern=f"^{CANCEL_PATTERN}$")
                ]
            },
            fallbacks=[CommandHandler("cancel", self.conversation_manager.cancel)]
        )
        self.dispatcher.add_handler(add_watchlater_conv)
        
        # Command button handlers
        self.dispatcher.add_handler(CallbackQueryHandler(self.handle_command_button, pattern="^command_"))
        
        # Watch later action handlers
        self.dispatcher.add_handler(CallbackQueryHandler(self.watch_later_handlers.handle_watch_later_actions, pattern="^(move_watching_|watchlist_series_)"))
        
        # Mark watched handlers
        self.dispatcher.add_handler(CallbackQueryHandler(self.watchlist_handlers.mark_watched_callback, pattern="^mark_watched_"))
        
        # Remove series handlers
        self.dispatcher.add_handler(CallbackQueryHandler(self.watchlist_handlers.remove_series_callback, pattern="^remove_series_"))

        # Add error handler
        self.dispatcher.add_error_handler(self.error_handler)
        
    def start(self, update: Update, context: CallbackContext) -> None:
        """Send a message when the command /start is issued."""
        user = update.effective_user
        
        # Add user to database or update if exists
        self.db.add_user(
            user.id,
            user.username,
            user.first_name,
            user.last_name
        )
        
        # Create inline keyboard with primary commands
        keyboard = [
            [
                InlineKeyboardButton("Добавить сериал в список", callback_data="command_add"),
                InlineKeyboardButton("Сериалы в процессе", callback_data="command_list")
            ],
            [
                InlineKeyboardButton("Просмотренные сериалы", callback_data="command_watched")
            ],
            [
                InlineKeyboardButton("Помощь", callback_data="command_help")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        welcome_text = (
            f"Привет, {user.first_name}! 👋\n\n"
            f"Я ваш персональный трекер сериалов. Я помогу вам отслеживать, какие сериалы вы смотрите. "
            f"В будущем мы добавим возможность сохранять сериалы, которые вы планируете посмотреть, и проверять список уже просмотренных сериалов.\n\n"
            f"Вы можете получить доступ ко всем командам, нажав кнопку меню в нашем чате или используя кнопки ниже:"
        )
        
        # Determine if this is from a callback or direct command
        if update.callback_query:
            update.callback_query.answer()
            update.callback_query.edit_message_text(welcome_text, reply_markup=reply_markup)
        else:
            update.message.reply_text(welcome_text, reply_markup=reply_markup)
        
    def help_command(self, update: Update, context: CallbackContext) -> None:
        """Send a message when the command /help is issued."""
        # Create inline keyboard with primary commands
        keyboard = [
            [
                InlineKeyboardButton("Добавить сериал в список", callback_data="command_add"),
                InlineKeyboardButton("Сериалы в процессе", callback_data="command_list")
            ],
            [
                InlineKeyboardButton("Просмотренные сериалы", callback_data="command_watched")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        help_text = (
            "Вот команды, которые вы можете использовать:\n\n"
            "*Отслеживание сериалов, которые вы смотрите*\n"
            "/addinwatchlist - Добавить новый сериал для отслеживания прогресса\n"
            "/watchlist - Показать все сериалы, которые вы сейчас смотрите\n"
            "/watched - Показать все просмотренные сериалы\n"
            "/help - Показать это сообщение справки\n\n"
            "*Дополнительно*\n"
            "/addwatched - Добавить сериал, который вы уже посмотрели\n"
            "\nВы также можете получить доступ к этим командам в любое время, нажав кнопку меню (☰) в нашем чате."
        )
        
        # Determine if this is from a callback or direct command
        if update.callback_query:
            update.callback_query.answer()
            update.callback_query.edit_message_text(help_text, parse_mode='Markdown', reply_markup=reply_markup)
        else:
            update.message.reply_text(help_text, parse_mode='Markdown', reply_markup=reply_markup)
        
    def list_series(self, update: Update, context: CallbackContext) -> None:
        """List all TV series the user is watching."""
        return self.watchlist_handlers.list_series(update, context)
        
    def error_handler(self, update: Update, context: CallbackContext) -> None:
        """Log errors caused by updates."""
        logger.error(f"Update {update} caused error {context.error}")
        
        # Notify user if possible
        if update and update.effective_chat:
            context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Извините, произошла ошибка. Пожалуйста, попробуйте снова или свяжитесь с разработчиком, если проблема сохраняется."
            )
        
    def start_bot(self, use_webhook=True):
        """Start the bot."""
        # Start the notification scheduler
        self.scheduler.start()
        
        # Get port from environment variable (Render sets this)
        port = int(os.getenv('PORT', '10000'))
        
        if use_webhook:
            # Webhook configuration
            webhook_url = os.getenv('WEBHOOK_URL')
            
            if not webhook_url:
                logger.warning("WEBHOOK_URL environment variable is not set. Falling back to polling mode with health check server.")
                # Start Flask server in a separate thread
                flask_thread = threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port))
                flask_thread.daemon = True
                flask_thread.start()
                
                # Clear any existing webhooks
                self.updater.bot.delete_webhook()
                
                # Start polling
                self.updater.start_polling(drop_pending_updates=True)
                logger.info(f"Bot started in polling mode with health check server on port {port}")
            else:
                # Start webhook
                self.updater.start_webhook(
                    listen='0.0.0.0',
                    port=port,
                    url_path=os.getenv('TELEGRAM_BOT_TOKEN'),
                    webhook_url=f"{webhook_url}/{os.getenv('TELEGRAM_BOT_TOKEN')}",
                    drop_pending_updates=True
                )
                logger.info(f"Bot started in webhook mode on port {port}")
        else:
            # Start Flask server in a separate thread for health checks
            flask_thread = threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port))
            flask_thread.daemon = True
            flask_thread.start()
            
            # Clear any existing webhooks
            self.updater.bot.delete_webhook()
            
            # Start polling
            self.updater.start_polling(drop_pending_updates=True)
            logger.info(f"Bot started in polling mode with health check server on port {port}")
        
        # Run the bot until the user presses Ctrl+C
        self.updater.idle()
        
        # Stop the scheduler
        self.scheduler.stop()
        
        # Close database connections
        self.db.close()
        
    def view_watch_later_list(self, update: Update, context: CallbackContext) -> None:
        """View the user's watchlist"""
        self.watch_later_handlers.view_watch_later_start(update, context)
        
    def handle_command_button(self, update: Update, context: CallbackContext) -> None:
        """Handle command buttons."""
        query = update.callback_query
        command = query.data.split('_')[1]
        logger.info(f"Command button pressed: {command}")

        if command == 'add':
            logger.info("Starting add series process...")
            query.answer("Starting add series process...")
            return self.watchlist_handlers.add_series_start(update, context)
        elif command == 'list':
            logger.info("Showing series list...")
            query.answer("Showing series list...")
            return self.list_series(update, context)
        elif command == 'watchlist':
            logger.info("Showing watchlist...")
            query.answer("Showing watchlist...")
            return self.watch_later_handlers.view_watch_later_start(update, context)
        elif command == 'watched':
            logger.info("Showing watched series...")
            query.answer("Showing watched series...")
            return self.watched_handlers.list_watched(update, context)
        elif command == 'update':
            logger.info("Starting update progress process...")
            query.answer("Starting update progress process...")
            return self.conversation_manager.update_progress_start(update, context)
        elif command == 'help':
            logger.info("Showing help...")
            query.answer("Showing help...")
            return self.help_command(update, context)
        elif command == 'addwatched':
            logger.info("Starting add watched series process...")
            query.answer("Starting add watched series process...")
            return self.watched_handlers.add_watched_series_start(update, context)
        else:
            logger.warning(f"Unknown command button: {command}")
            query.answer("Unknown command")
            return ConversationHandler.END

def main():
    """Start the bot."""
    bot = SeriesTrackerBot(os.getenv('TELEGRAM_BOT_TOKEN'), DBHandler(), TMDBApi())
    # Use webhook in production, polling in development
    use_webhook = os.getenv('ENVIRONMENT', 'development').lower() == 'production'
    bot.start_bot(use_webhook)
    
if __name__ == '__main__':
    main() 