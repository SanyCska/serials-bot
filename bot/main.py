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

from bot.database.models import init_db
from bot.database.db_handler import DBHandler
from bot.tmdb_api import TMDBApi
from bot.scheduler import NotificationScheduler
from bot.conversations import (
    ConversationManager,
    SELECTING_SERIES,
    SELECTING_SEASON,
    SELECTING_EPISODE,
    MANUAL_EPISODE_ENTRY,
    MANUAL_SERIES_NAME,
    MANUAL_SERIES_YEAR,
    MANUAL_SERIES_SEASONS,
    CANCEL_PATTERN,
    SEARCH_WATCHED,
    SERIES_SELECTION,
    SELECT_SEASON,
    SELECT_EPISODE,
    MARK_WATCHED,
    MANUAL_SEASON_ENTRY,
    SERIES_PATTERN,
    SEASON_PATTERN,
    EPISODE_PATTERN,
    MANUAL_ADD_PATTERN,
    MANUAL_SEASON_PATTERN,
    MANUAL_ENTRY_PATTERN,
)

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
    def __init__(self):
        # Initialize database
        init_db()
        
        # Initialize handlers
        self.db = DBHandler()
        self.tmdb = TMDBApi()
        self.conversation_manager = ConversationManager()
        
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
            ('start', 'Start the bot'),
            ('help', 'Show help message'),
            ('addinwatchlist', "Add a new series you're watching"),
            ('watchlist', 'Series in progress'),
            # ('watchlater', 'Add series you plan to watch'),
            # ('addinwatchlater', 'Add a series you plan to watch'),
            # ('watched', 'List all watched series'),
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
        self.dispatcher.add_handler(CommandHandler("watchlater", self.conversation_manager.view_watchlist_start))
        self.dispatcher.add_handler(CommandHandler("addinwatchlater", self.conversation_manager.add_to_watchlist_start))
        self.dispatcher.add_handler(CommandHandler("addwatched", self.conversation_manager.add_watched_series_start))
        self.dispatcher.add_handler(CommandHandler("markwatched", self.conversation_manager.mark_watched_start))
        
        # Add series conversation handler
        add_series_conv = ConversationHandler(
            entry_points=[
                CommandHandler("add", self.conversation_manager.add_series_start),
                CommandHandler("addinwatchlist", self.conversation_manager.add_series_start),
                CallbackQueryHandler(self.conversation_manager.add_series_start, pattern="^command_add$")
            ],
            states={
                SELECTING_SERIES: [
                    MessageHandler(Filters.text & ~Filters.command, self.conversation_manager.search_series),
                    CallbackQueryHandler(self.conversation_manager.series_selected, pattern=f"^{SERIES_PATTERN.format('.*')}$"),
                    CallbackQueryHandler(self.conversation_manager.manual_series_name_prompt, pattern=f"^{MANUAL_ADD_PATTERN}$")
                ],
                MANUAL_SERIES_NAME: [
                    MessageHandler(Filters.text & ~Filters.command, self.conversation_manager.manual_series_name_entered)
                ],
                MANUAL_SERIES_YEAR: [
                    MessageHandler(Filters.text & ~Filters.command, self.conversation_manager.manual_series_year_entered)
                ],
                MANUAL_SERIES_SEASONS: [
                    MessageHandler(Filters.text & ~Filters.command, self.conversation_manager.manual_series_seasons_entered)
                ],
                SELECTING_SEASON: [
                    CallbackQueryHandler(self.conversation_manager.season_selected, pattern=f"^{SEASON_PATTERN.format('.*', '.*')}$"),
                    CallbackQueryHandler(self.conversation_manager.manual_season_entry, pattern=f"^{MANUAL_SEASON_PATTERN.format('.*')}$")
                ],
                MANUAL_SEASON_ENTRY: [
                    MessageHandler(Filters.text & ~Filters.command, self.conversation_manager.manual_season_entry)
                ],
                SELECTING_EPISODE: [
                    CallbackQueryHandler(self.conversation_manager.episode_selected, pattern=f"^{EPISODE_PATTERN.format('.*', '.*', '.*')}$"),
                    CallbackQueryHandler(self.conversation_manager.manual_episode_entry, pattern=f"^{MANUAL_ENTRY_PATTERN.format('.*', '.*')}$")
                ],
                MANUAL_EPISODE_ENTRY: [
                    MessageHandler(Filters.text & ~Filters.command, self.conversation_manager.manual_episode_entry)
                ]
            },
            fallbacks=[CommandHandler("cancel", self.conversation_manager.cancel)]
        )
        
        # Add the conversation handler to dispatcher
        self.dispatcher.add_handler(add_series_conv)
        
        # Update progress conversation handler
        update_progress_conv = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(self.conversation_manager.update_progress_start, pattern="^command_update$")
            ],
            states={
                SELECTING_SERIES: [
                    CallbackQueryHandler(self.conversation_manager.update_progress_series_selected, pattern="^update_series_.*$")
                ],
                SELECTING_SEASON: [
                    CallbackQueryHandler(self.conversation_manager.season_selected, pattern=f"^{SEASON_PATTERN.format('.*', '.*')}$"),
                    CallbackQueryHandler(self.conversation_manager.manual_season_entry, pattern=f"^{MANUAL_SEASON_PATTERN.format('.*')}$")
                ],
                MANUAL_SEASON_ENTRY: [
                    MessageHandler(Filters.text & ~Filters.command, self.conversation_manager.manual_season_entry)
                ],
                SELECTING_EPISODE: [
                    CallbackQueryHandler(self.conversation_manager.episode_selected, pattern=f"^{EPISODE_PATTERN.format('.*', '.*', '.*')}$"),
                    CallbackQueryHandler(self.conversation_manager.manual_episode_entry, pattern=f"^{MANUAL_ENTRY_PATTERN.format('.*', '.*')}$")
                ],
                MANUAL_EPISODE_ENTRY: [
                    MessageHandler(Filters.text & ~Filters.command, self.conversation_manager.manual_episode_entry)
                ]
            },
            fallbacks=[CommandHandler("cancel", self.conversation_manager.cancel)]
        )
        self.dispatcher.add_handler(update_progress_conv)
        
        # Command button handlers
        self.dispatcher.add_handler(CallbackQueryHandler(self.handle_command_button, pattern="^command_"))
        
        # Watchlist action handlers
        self.dispatcher.add_handler(CallbackQueryHandler(self.conversation_manager.handle_watchlist_actions, pattern="^(move_watching_|watchlist_series_)"))
        
        # Mark watched handlers
        self.dispatcher.add_handler(CallbackQueryHandler(self.mark_watched_callback, pattern="^mark_watched_"))
        
        # Remove series handlers
        self.dispatcher.add_handler(CallbackQueryHandler(self.remove_series_callback, pattern="^remove_series_"))

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
                InlineKeyboardButton("Add series in watchlist", callback_data="command_add"),
                InlineKeyboardButton("Series in progress", callback_data="command_list")
            ],
            # [
            #     InlineKeyboardButton("Watch later", callback_data="command_watchlist")
            # ],
            [
                InlineKeyboardButton("Help", callback_data="command_help")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        update.message.reply_text(
            f"Hello {user.first_name}! 👋\n\n"
            f"I'm your personal TV Series Tracker. I'll help you keep track of which TV shows you're watching. "
            f"In future we will add possibility to save series you plan to watch and check the list of already watched series.\n\n"
            f"You can access all commands by clicking the menu button in our chat or by using the buttons below:",
            reply_markup=reply_markup
        )
        
    def help_command(self, update: Update, context: CallbackContext) -> None:
        """Send a message when the command /help is issued."""
        # Create inline keyboard with primary commands
        keyboard = [
            [
                InlineKeyboardButton("Add series in watchlist", callback_data="command_add"),
                InlineKeyboardButton("Series in progress", callback_data="command_list")
            ],
            # [
            #     InlineKeyboardButton("Watch later", callback_data="command_watchlist")
            # ],
            [
                InlineKeyboardButton("Help", callback_data="command_help")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        help_text = (
            "Here are the commands you can use:\n\n"
            "*Tracking Series You're Watching*\n"
            "/addinwatchlist - Add a new TV series to track your watching progress\n"
            "/watchlist - List all TV series you're currently watching\n"
            # "/watchlist - View series in your future watchlist\n"
            # "/addwatch - Add a series to your future watchlist\n\n"
            # "/watched - List all watched series\n"
            # "/addwatched - Add a new watched series\n\n"
            "/help - Show this help message\n\n"
            "You can also access these commands anytime by clicking the menu button (☰) in our chat."
        )
        
        # Determine if this is from a callback or direct command
        if update.callback_query:
            update.callback_query.answer()
            update.callback_query.edit_message_text(help_text, parse_mode='Markdown', reply_markup=reply_markup)
        else:
            update.message.reply_text(help_text, parse_mode='Markdown', reply_markup=reply_markup)
        
    def list_series(self, update: Update, context: CallbackContext) -> None:
        """List all TV series the user is watching."""
        logger.info(f"List command received from user {update.effective_user.id}")
        user = self.db.get_user(update.effective_user.id)
        
        if not user:
            logger.warning(f"User not found in database for telegram_id: {update.effective_user.id}")
            # Create keyboard with options
            keyboard = [
                [InlineKeyboardButton("Add Series", callback_data="command_add")],
                [InlineKeyboardButton("Watch later", callback_data="command_watchlist")],
                [InlineKeyboardButton("Help", callback_data="command_help")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            update.message.reply_text(
                "You need to add a series first. Use /add command or the button below.",
                reply_markup=reply_markup
            )
            return
            
        user_series_list = self.db.get_user_series_list(user.id)
        logger.info(f"Retrieved {len(user_series_list) if user_series_list else 0} series for user {user.id}")
        
        if not user_series_list:
            logger.info(f"No series found for user {user.id}")
            # Create keyboard with options
            keyboard = [
                [InlineKeyboardButton("Add Series", callback_data="command_add")],
                [InlineKeyboardButton("Watch later", callback_data="command_watchlist")],
                [InlineKeyboardButton("Help", callback_data="command_help")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            update.message.reply_text(
                "You're not watching any series yet. Use /addinwatchlist command or the button below.",
                reply_markup=reply_markup
            )
            return
            
        # Send header message
        try:
            update.message.reply_text("*Your TV Series Watchlist:*", parse_mode=ParseMode.MARKDOWN)
            logger.info("Sent header message")
        except Exception as e:
            logger.error(f"Error sending header message: {e}")
            return
        
        # Send each series as a separate message
        for user_series, series in user_series_list:
            try:
                year_str = f" ({series.year})" if series.year else ""
                message = f"• *{series.name}*{year_str}\n"
                message += f"  Currently at: Season {user_series.current_season}, Episode {user_series.current_episode}"
                
                # Show the 'Watched' and 'Remove' buttons for each series
                keyboard = [
                    [
                        InlineKeyboardButton(f"✅ Watched", callback_data=f"mark_watched_{series.id}"),
                        InlineKeyboardButton(f"❌ Remove", callback_data=f"remove_series_{series.id}")
                    ]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
                logger.info(f"Sent message for series: {series.name}")
            except Exception as e:
                logger.error(f"Error sending message for series {series.name}: {e}")
        
        # Send footer with common actions
        try:
            keyboard = [
                [
                    InlineKeyboardButton("➕ Add Series", callback_data="command_add"),
                    InlineKeyboardButton("📝 Update Progress", callback_data="command_update")
                ],
                [
                    InlineKeyboardButton("📺 Watch later", callback_data="command_watchlist"),
                    InlineKeyboardButton("❓ Help", callback_data="command_help")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            update.message.reply_text("*Actions:*", parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
            logger.info("Sent footer message with actions")
        except Exception as e:
            logger.error(f"Error sending footer message: {e}")
        
    def error_handler(self, update: Update, context: CallbackContext) -> None:
        """Log errors caused by updates."""
        logger.error(f"Update {update} caused error {context.error}")
        
        # Notify user if possible
        if update and update.effective_chat:
            context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="Sorry, an error occurred. Please try again or contact the developer if the problem persists."
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
        
    def view_watchlist(self, update: Update, context: CallbackContext) -> None:
        """View the user's watchlist"""
        self.conversation_manager.view_watchlist_start(update, context)
        
    def handle_command_button(self, update: Update, context: CallbackContext) -> None:
        """Handle command buttons."""
        query = update.callback_query
        command = query.data.split('_')[1]
        logger.info(f"Command button pressed: {command}")
        
        if command == 'add':
            logger.info("Starting add series process...")
            query.answer("Starting add series process...")
            return self.conversation_manager.add_series_start(update, context)
        elif command == 'addwatch':
            logger.info("Starting add to watchlist process...")
            query.answer("Starting add to watchlist process...")
            return self.conversation_manager.add_to_watchlist_start(update, context)
        elif command == 'list':
            logger.info("Showing series list...")
            query.answer("Showing series list...")
            return self.list_series(update, context)
        elif command == 'watchlist':
            logger.info("Showing watchlist...")
            query.answer("Showing watchlist...")
            return self.conversation_manager.view_watchlist_start(update, context)
        elif command == 'help':
            logger.info("Showing help...")
            query.answer("Showing help...")
            return self.help_command(update, context)
        elif command == 'addwatched':
            logger.info("Starting add watched series process...")
            query.answer("Starting add watched series process...")
            return self.conversation_manager.add_watched_series_start(update, context)
        elif command == 'update':
            logger.info("Starting update progress process...")
            query.answer("Starting update progress process...")
            return self.conversation_manager.update_progress_start(update, context)
        else:
            logger.warning(f"Unknown command button: {command}")
            query.answer("Unknown command")
            return ConversationHandler.END
        
    def list_series_callback(self, update: Update, context: CallbackContext) -> None:
        """List series from callback query"""
        query = update.callback_query
        logger.info(f"Processing list series callback for user {query.from_user.id}")
        
        try:
            user = self.db.get_user(query.from_user.id)
            
            if not user:
                logger.warning(f"User not found for telegram_id: {query.from_user.id}")
                # Create keyboard with options
                keyboard = [
                    [InlineKeyboardButton("Add Series", callback_data="command_add")],
                    [InlineKeyboardButton("Watch later", callback_data="command_watchlist")],
                    [InlineKeyboardButton("Help", callback_data="command_help")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                query.edit_message_text(
                    "You need to add a series first. Use the Add Series button or /add command.",
                    reply_markup=reply_markup
                )
                return
                
            user_series_list = self.db.get_user_series_list(user.id)
            logger.info(f"Retrieved {len(user_series_list) if user_series_list else 0} series for user {user.id}")
            
            if not user_series_list:
                logger.info(f"No series found for user {user.id}")
                # Create keyboard with options
                keyboard = [
                    [InlineKeyboardButton("Add Series", callback_data="command_add")],
                    [InlineKeyboardButton("Watch later", callback_data="command_watchlist")],
                    [InlineKeyboardButton("Help", callback_data="command_help")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                query.edit_message_text(
                    "You're not watching any series yet. Use /addinwatchlist command or the button below.",
                    reply_markup=reply_markup
                )
                return
                
            # Edit current message to show header
            query.edit_message_text("*Your TV Series Watchlist:*", parse_mode=ParseMode.MARKDOWN)
            logger.info("Updated header message")
            
            # Send each series as a separate message
            for user_series, series in user_series_list:
                try:
                    year_str = f" ({series.year})" if series.year else ""
                    message = f"• *{series.name}*{year_str}\n"
                    message += f"  Currently at: Season {user_series.current_season}, Episode {user_series.current_episode}"
                    
                    # Only show the 'Watched' button for each series
                    keyboard = [
                        [
                            InlineKeyboardButton(f"✅ Watched", callback_data=f"mark_watched_{series.id}")
                        ]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    context.bot.send_message(
                        chat_id=query.message.chat_id,
                        text=message,
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=reply_markup
                    )
                    logger.info(f"Sent message for series: {series.name}")
                except Exception as e:
                    logger.error(f"Error sending message for series {series.name}: {e}")
            
            # Send footer with common actions
            try:
                keyboard = [
                    [
                        InlineKeyboardButton("➕ Add Series", callback_data="command_add"),
                        InlineKeyboardButton("📝 Update Progress", callback_data="command_update")
                    ],
                    [
                        InlineKeyboardButton("📺 Watch later", callback_data="command_watchlist"),
                        InlineKeyboardButton("❓ Help", callback_data="command_help")
                    ]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text="*Actions:*",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=reply_markup
                )
                logger.info("Sent footer message with actions")
            except Exception as e:
                logger.error(f"Error sending footer message: {e}")
        except Exception as e:
            logger.error(f"Error in list_series_callback: {e}", exc_info=True)
            query.answer("An error occurred. Please try again.")
        
    def check_updates_callback(self, update: Update, context: CallbackContext) -> None:
        """Check updates from callback query"""
        query = update.callback_query
        logger.info("Processing check updates callback")
        # Run a manual check
        result = self.scheduler.manual_check(query.from_user.id)
        logger.info(f"Manual check result for user {query.from_user.id}: {result}")
        # Add buttons for after check
        keyboard = [
            [
                InlineKeyboardButton("My List", callback_data="command_list"),
                InlineKeyboardButton("Update Progress", callback_data="command_update")
            ],
            [
                InlineKeyboardButton("Add Series", callback_data="command_add"),
                InlineKeyboardButton("Help", callback_data="command_help")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        try:
            query.edit_message_text(result, reply_markup=reply_markup)
        except Exception as e:
            logger.error(f"Error updating message with check results: {e}")
        
    def move_to_watchlist(self, update: Update, context: CallbackContext) -> None:
        """Move a series from watching to watchlist"""
        query = update.callback_query
        logger.info(f"Processing move to watchlist callback: {query.data}")
        query.answer()
        
        # Extract series ID from callback data
        try:
            series_id = int(query.data.split("_")[2])
            logger.info(f"Moving series ID {series_id} to watchlist")
        except (IndexError, ValueError) as e:
            logger.error(f"Error parsing series ID from callback data: {query.data}, error: {e}")
            query.edit_message_text("Error processing your request. Please try again.")
            return
        
        # Get user
        user = self.db.get_user(query.from_user.id)
        
        if not user:
            logger.error(f"User not found for telegram_id: {query.from_user.id}")
            query.edit_message_text("Error: User not found.")
            return
            
        # Get series name first for the success message
        series = None
        user_series_list = self.db.get_user_series_list(user.id)
        for user_series, s in user_series_list:
            if s.id == series_id:
                series = s
                break
                
        # Move the series to watchlist
        if self.db.move_to_watchlist(user.id, series_id):
            logger.info(f"Successfully moved series {series_id} to watchlist for user {user.id}")
            if series:
                # Create buttons for next actions
                keyboard = [
                    [
                        InlineKeyboardButton("Watch later", callback_data="command_watchlist"),
                        InlineKeyboardButton("My Series", callback_data="command_list")
                    ],
                    [
                        InlineKeyboardButton("Add More Series", callback_data="command_add"),
                        InlineKeyboardButton("Help", callback_data="command_help")
                    ]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                query.edit_message_text(
                    f"I've moved '{series.name}' to your watchlist for future viewing!",
                    reply_markup=reply_markup
                )
            else:
                query.edit_message_text("Series has been moved to your watchlist.")
        else:
            logger.error(f"Failed to move series {series_id} to watchlist for user {user.id}")
            query.edit_message_text("Error moving series. Please try again later.")
        
    def list_watched(self, update: Update, context: CallbackContext):
        """List all watched series for a user."""
        user = self.db.get_user(update.effective_user.id)
        
        if not user:
            update.message.reply_text("You haven't added any series yet. Use /addwatched to add your first watched series.")
            return
            
        series_list = self.db.get_user_series_list(user.id, watched_only=True)
        
        if not series_list:
            # Create keyboard with options
            keyboard = [
                [InlineKeyboardButton("Add Watched Series", callback_data="command_addwatched")],
                [InlineKeyboardButton("View Watching List", callback_data="command_list")],
                [InlineKeyboardButton("Watch later", callback_data="command_watchlist")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            update.message.reply_text(
                "You haven't marked any series as watched yet.\n"
                "Use /addwatched to add series you've already watched.",
                reply_markup=reply_markup
            )
            return
            
        message = "*Your Watched Series:*\n\n"
        
        # Create keyboard for actions
        keyboard = []
        
        for user_series, series in series_list:
            year_str = f" ({series.year})" if series.year else ""
            watched_date = user_series.watched_date.strftime("%Y-%m-%d") if user_series.watched_date else "Unknown date"
            message += f"• *{series.name}*{year_str}\n"
            message += f"  Completed on: {watched_date}\n\n"
        
        # Add action buttons
        keyboard.append([
            InlineKeyboardButton("Add More Watched", callback_data="command_addwatched"),
            InlineKeyboardButton("View Watching", callback_data="command_list")
        ])
        keyboard.append([
            InlineKeyboardButton("Watch later", callback_data="command_watchlist"),
            InlineKeyboardButton("Help", callback_data="command_help")
        ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        update.message.reply_text(
            message,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
        
    def mark_watched_callback(self, update: Update, context: CallbackContext) -> None:
        """Handle marking a series as watched."""
        query = update.callback_query
        query.answer()
        
        try:
            series_id = int(query.data.split('_')[2])
            user = self.db.get_user(query.from_user.id)
            
            if not user:
                query.edit_message_text("Error: User not found.")
                return
            
            # Get series name before marking as watched
            user_series_list = self.db.get_user_series_list(user.id)
            series_name = None
            for user_series, s in user_series_list:
                if s.id == series_id:
                    series_name = s.name
                    break
            
            # Mark the series as watched
            if self.db.mark_as_watched(user.id, series_id):
                message = f"✅ I've marked '{series_name}' as watched and moved it to your watched list!"
                
                query.edit_message_text(message)
            else:
                query.edit_message_text("Error marking series as watched. Please try again later.")
        except Exception as e:
            logger.error(f"Error marking series as watched: {e}", exc_info=True)
            query.edit_message_text("An error occurred while marking the series as watched. Please try again.")
        
    def remove_series_callback(self, update: Update, context: CallbackContext) -> None:
        """Handle removing a series from the user's watching list."""
        query = update.callback_query
        query.answer()
        try:
            series_id = int(query.data.split('_')[2])
            user = self.db.get_user(query.from_user.id)
            if not user:
                query.edit_message_text("Error: User not found.")
                return
            # Remove the series from user's watching list
            removed = self.db.remove_user_series(user.id, series_id)
            if removed:
                query.edit_message_text("✅ Series has been removed from your watching list.")
            else:
                query.edit_message_text("❌ Failed to remove the series. Please try again later.")
        except Exception as e:
            logger.error(f"Error removing series: {e}", exc_info=True)
            query.edit_message_text("An error occurred while removing the series. Please try again.")
        
def main():
    """Start the bot."""
    bot = SeriesTrackerBot()
    # Use webhook in production, polling in development
    use_webhook = os.getenv('ENVIRONMENT', 'development').lower() == 'production'
    bot.start_bot(use_webhook)
    
if __name__ == '__main__':
    main() 