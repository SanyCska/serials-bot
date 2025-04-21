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
)

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

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
        self._register_handlers()
        
    def _set_commands(self):
        """Set the commands menu for the bot"""
        bot_commands = [
            ('start', 'Start the bot'),
            ('help', 'Show help message'),
            ('add', 'Add a new TV series to your watchlist'),
            ('list', 'List all TV series you are watching'),
            ('update', 'Update your progress on a series'),
            ('remove', 'Remove a series from your watchlist'),
            ('check', 'Check for new episodes or seasons'),
            ('watchlist', 'View your future watchlist'),
            ('addwatch', 'Add a series to your future watchlist'),
            ('watched', 'List all watched series'),
            ('addwatched', 'Add a new watched series'),
        ]
        
        self.updater.bot.set_my_commands(bot_commands)
        logger.info("Bot commands menu set up successfully")
        
    def _register_handlers(self):
        """Register all command and conversation handlers."""
        # Basic command handlers
        self.dispatcher.add_handler(CommandHandler('start', self.start))
        self.dispatcher.add_handler(CommandHandler('help', self.help))
        self.dispatcher.add_handler(CommandHandler('list', self.list_series))
        self.dispatcher.add_handler(CommandHandler('check', self.check_updates))
        self.dispatcher.add_handler(CommandHandler('watchlist', self.view_watchlist))
        self.dispatcher.add_handler(CommandHandler('watched', self.list_watched))
        
        # Add mark watched handler
        self.dispatcher.add_handler(CallbackQueryHandler(self.mark_watched_callback, pattern=r'^mark_watched_'))
        
        # Add watched series conversation handler (needs to be before the command buttons handler)
        add_watched_conv = ConversationHandler(
            entry_points=[
                CommandHandler('addwatched', self.conversation_manager.add_watched_series_start),
                CallbackQueryHandler(self.conversation_manager.add_watched_series_start, pattern=r'^command_addwatched$')
            ],
            states={
                SELECTING_SERIES: [
                    MessageHandler(Filters.text & ~Filters.command, self.conversation_manager.search_series),
                    CallbackQueryHandler(self.conversation_manager.series_selected, pattern=r'^series_|^manual_add$|^cancel$'),
                ],
                SEARCH_WATCHED: [
                    MessageHandler(Filters.text & ~Filters.command, self.conversation_manager.search_watched_series)
                ],
                MANUAL_SERIES_NAME: [
                    MessageHandler(Filters.text & ~Filters.command, self.conversation_manager.manual_series_name_entered),
                ],
                MANUAL_SERIES_YEAR: [
                    MessageHandler(Filters.text & ~Filters.command, self.conversation_manager.manual_series_year_entered),
                ],
                MANUAL_SERIES_SEASONS: [
                    MessageHandler(Filters.text & ~Filters.command, self.conversation_manager.manual_series_seasons_entered),
                ],
            },
            fallbacks=[
                CommandHandler('cancel', self.conversation_manager.cancel),
                CallbackQueryHandler(self.conversation_manager.cancel, pattern=r'^cancel$')
            ],
        )
        self.dispatcher.add_handler(add_watched_conv)
        
        # Command buttons handler
        self.dispatcher.add_handler(CallbackQueryHandler(self.handle_command_button, pattern=r'^command_'))
        
        # Move to watchlist handler
        self.dispatcher.add_handler(CallbackQueryHandler(self.move_to_watchlist, pattern=r'^move_watchlist_'))
        
        # Add series conversation
        add_series_conv = ConversationHandler(
            entry_points=[CommandHandler('add', self.conversation_manager.add_series_start)],
            states={
                SELECTING_SERIES: [
                    MessageHandler(Filters.text & ~Filters.command, self.conversation_manager.search_series),
                    CallbackQueryHandler(self.conversation_manager.series_selected, pattern=r'^series_|^manual_add$|^cancel$'),
                ],
                SELECTING_SEASON: [
                    CallbackQueryHandler(self.conversation_manager.season_selected, pattern=r'^season_|^cancel$'),
                ],
                SELECTING_EPISODE: [
                    CallbackQueryHandler(self.conversation_manager.episode_selected, pattern=r'^(episode_|manual_|cancel$)'),
                ],
                MANUAL_EPISODE_ENTRY: [
                    MessageHandler(Filters.text & ~Filters.command, self.conversation_manager.manual_episode_entry),
                ],
                MANUAL_SERIES_NAME: [
                    MessageHandler(Filters.text & ~Filters.command, self.conversation_manager.manual_series_name_entered),
                ],
                MANUAL_SERIES_YEAR: [
                    MessageHandler(Filters.text & ~Filters.command, self.conversation_manager.manual_series_year_entered),
                ],
                MANUAL_SERIES_SEASONS: [
                    MessageHandler(Filters.text & ~Filters.command, self.conversation_manager.manual_series_seasons_entered),
                ],
            },
            fallbacks=[CommandHandler('cancel', self.conversation_manager.cancel)],
        )
        self.dispatcher.add_handler(add_series_conv)
        
        # Add to watchlist conversation
        add_to_watchlist_conv = ConversationHandler(
            entry_points=[CommandHandler('addwatch', self.conversation_manager.add_to_watchlist_start)],
            states={
                SELECTING_SERIES: [
                    MessageHandler(Filters.text & ~Filters.command, self.conversation_manager.search_series),
                    CallbackQueryHandler(self.conversation_manager.series_selected, pattern=r'^series_|^manual_add$|^cancel$'),
                ],
                MANUAL_SERIES_NAME: [
                    MessageHandler(Filters.text & ~Filters.command, self.conversation_manager.manual_series_name_entered),
                ],
                MANUAL_SERIES_YEAR: [
                    MessageHandler(Filters.text & ~Filters.command, self.conversation_manager.manual_series_year_entered),
                ],
                MANUAL_SERIES_SEASONS: [
                    MessageHandler(Filters.text & ~Filters.command, self.conversation_manager.manual_series_seasons_entered),
                ],
            },
            fallbacks=[CommandHandler('cancel', self.conversation_manager.cancel)],
        )
        self.dispatcher.add_handler(add_to_watchlist_conv)
        
        # Watchlist actions handler (outside of conversation handler)
        self.dispatcher.add_handler(
            CallbackQueryHandler(
                self.conversation_manager.handle_watchlist_actions,
                pattern=r'^(watchlist_series_|move_watching_)'
            )
        )
        
        # Watchlist view handler
        self.dispatcher.add_handler(CommandHandler('watchlist', self.conversation_manager.view_watchlist_start))
        
        # Update series conversation
        update_series_conv = ConversationHandler(
            entry_points=[CommandHandler('update', self.conversation_manager.update_series_start)],
            states={
                SELECTING_SERIES: [
                    CallbackQueryHandler(self.conversation_manager.series_selected, pattern=r'^series_|^cancel$'),
                ],
                SELECTING_SEASON: [
                    CallbackQueryHandler(self.conversation_manager.season_selected, pattern=r'^season_|^cancel$'),
                ],
                SELECTING_EPISODE: [
                    CallbackQueryHandler(self.conversation_manager.episode_selected, pattern=r'^(episode_|manual_|cancel$)'),
                ],
                MANUAL_EPISODE_ENTRY: [
                    MessageHandler(Filters.text & ~Filters.command, self.conversation_manager.manual_episode_entry),
                ],
            },
            fallbacks=[CommandHandler('cancel', self.conversation_manager.cancel)],
        )
        self.dispatcher.add_handler(update_series_conv)
        
        # Remove series conversation
        remove_series_conv = ConversationHandler(
            entry_points=[CommandHandler('remove', self.conversation_manager.remove_series_start)],
            states={
                SELECTING_SERIES: [
                    CallbackQueryHandler(self.remove_series, pattern=r'^series_|^cancel$'),
                ],
            },
            fallbacks=[CommandHandler('cancel', self.conversation_manager.cancel)],
        )
        self.dispatcher.add_handler(remove_series_conv)
        
        # Error handler
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
                InlineKeyboardButton("Add Series", callback_data="command_add"),
                InlineKeyboardButton("My List", callback_data="command_list")
            ],
            [
                InlineKeyboardButton("Check Updates", callback_data="command_check"),
                InlineKeyboardButton("My Watchlist", callback_data="command_watchlist")
            ],
            [
                InlineKeyboardButton("Help", callback_data="command_help")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        update.message.reply_text(
            f"Hello {user.first_name}! 👋\n\n"
            f"I'm your personal TV Series Tracker. I'll help you keep track of which TV shows you're watching "
            f"and notify you when new episodes or seasons are released.\n\n"
            f"You can also maintain a watchlist of series you plan to watch in the future.\n\n"
            f"You can access all commands by clicking the menu button in our chat or by using the buttons below:",
            reply_markup=reply_markup
        )
        
    def help(self, update: Update, context: CallbackContext) -> None:
        """Send a message when the command /help is issued."""
        # Create inline keyboard with primary commands
        keyboard = [
            [
                InlineKeyboardButton("Add Series", callback_data="command_add"),
                InlineKeyboardButton("My List", callback_data="command_list")
            ],
            [
                InlineKeyboardButton("Update Progress", callback_data="command_update"),
                InlineKeyboardButton("Remove Series", callback_data="command_remove")
            ],
            [
                InlineKeyboardButton("Check Updates", callback_data="command_check"),
                InlineKeyboardButton("My Watchlist", callback_data="command_watchlist")
            ],
            [
                InlineKeyboardButton("Add to Watchlist", callback_data="command_addwatch")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        help_text = (
            "Here are the commands you can use:\n\n"
            "*Tracking Series You're Watching*\n"
            "/add - Add a new TV series to track your watching progress\n"
            "/list - List all TV series you're currently watching\n"
            "/update - Update your progress on a series\n"
            "/remove - Remove a series from your list\n"
            "/check - Check for new episodes or seasons\n\n"
            "*Watchlist (Series to Watch Later)*\n"
            "/watchlist - View series in your future watchlist\n"
            "/addwatch - Add a series to your future watchlist\n\n"
            "/watched - List all watched series\n"
            "/addwatched - Add a new watched series\n\n"
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
        user = self.db.get_user(update.effective_user.id)
        
        if not user:
            # Create keyboard with options
            keyboard = [
                [InlineKeyboardButton("Add Series", callback_data="command_add")],
                [InlineKeyboardButton("View Watchlist", callback_data="command_watchlist")],
                [InlineKeyboardButton("Help", callback_data="command_help")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            update.message.reply_text(
                "You need to add a series first. Use /add command or the button below.",
                reply_markup=reply_markup
            )
            return
            
        user_series_list = self.db.get_user_series_list(user.id)
        
        if not user_series_list:
            # Create keyboard with options
            keyboard = [
                [InlineKeyboardButton("Add Series", callback_data="command_add")],
                [InlineKeyboardButton("View Watchlist", callback_data="command_watchlist")],
                [InlineKeyboardButton("Help", callback_data="command_help")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            update.message.reply_text(
                "You're not watching any series yet. Use /add command or the button below.",
                reply_markup=reply_markup
            )
            return
            
        # Send header message
        update.message.reply_text("*Your TV Series Watchlist:*", parse_mode=ParseMode.MARKDOWN)
        
        # Send each series as a separate message
        for user_series, series in user_series_list:
            year_str = f" ({series.year})" if series.year else ""
            message = f"• *{series.name}*{year_str}\n"
            message += f"  Currently at: Season {user_series.current_season}, Episode {user_series.current_episode}"
            
            # Create buttons for updating progress and marking as watched
            keyboard = [
                [
                    InlineKeyboardButton(f"📝 Update", callback_data=f"series_{series.tmdb_id}"),
                    InlineKeyboardButton(f"✅ Watched", callback_data=f"mark_watched_{series.id}")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
        
        # Send footer with common actions
        keyboard = [
            [
                InlineKeyboardButton("➕ Add Series", callback_data="command_add"),
                InlineKeyboardButton("🔄 Check Updates", callback_data="command_check")
            ],
            [
                InlineKeyboardButton("📺 My Watchlist", callback_data="command_watchlist"),
                InlineKeyboardButton("❓ Help", callback_data="command_help")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        update.message.reply_text("*Actions:*", parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
        
    def check_updates(self, update: Update, context: CallbackContext) -> None:
        """Manually check for updates."""
        update.message.reply_text("Checking for new episodes and seasons...")
        
        # Run a manual check
        result = self.scheduler.manual_check(update.effective_user.id)
        
        update.message.reply_text(result)
        
    def remove_series(self, update: Update, context: CallbackContext) -> int:
        """Remove a series from the user's watchlist."""
        query = update.callback_query
        query.answer()
        
        if query.data == CANCEL_PATTERN:
            query.edit_message_text("Operation cancelled.")
            return ConversationHandler.END
            
        # Extract series ID from callback data
        series_id = int(query.data.split("_")[1])
        
        # Get user
        user = self.db.get_user(query.from_user.id)
        
        if not user:
            query.edit_message_text("Error: User not found.")
            return ConversationHandler.END
            
        # Get series name first for the success message
        series = None
        user_series_list = self.db.get_user_series_list(user.id)
        for user_series, s in user_series_list:
            if s.id == series_id:
                series = s
                break
                
        # Remove the series from user's watchlist
        if self.db.remove_user_series(user.id, series_id):
            if series:
                query.edit_message_text(f"I've removed '{series.name}' from your watchlist.")
            else:
                query.edit_message_text("Series has been removed from your watchlist.")
        else:
            query.edit_message_text("Error removing series. Please try again later.")
            
        return ConversationHandler.END
        
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
        
        if use_webhook:
            # Webhook configuration
            port = int(os.getenv('PORT', 8443))
            webhook_url = os.getenv('WEBHOOK_URL')
            
            if not webhook_url:
                logger.error("WEBHOOK_URL environment variable is not set. Falling back to polling mode.")
                self.start_bot(use_webhook=False)
                return
                
            # Start webhook
            self.updater.start_webhook(
                listen='0.0.0.0',
                port=port,
                url_path=os.getenv('TELEGRAM_BOT_TOKEN'),
                webhook_url=f"{webhook_url}/{os.getenv('TELEGRAM_BOT_TOKEN')}"
            )
            logger.info(f"Bot started in webhook mode on port {port}")
        else:
            # Start polling
            self.updater.start_polling()
            logger.info("Bot started in polling mode. Press Ctrl+C to stop.")
        
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
        """Handle command buttons from inline keyboards"""
        query = update.callback_query
        command = query.data.split('_')[1]
        
        # Execute appropriate command based on button pressed
        if command == 'add':
            query.answer("Starting add series process...")
            return self.conversation_manager.add_series_start(update, context)
        elif command == 'addwatch':
            query.answer("Starting add to watchlist process...")
            return self.conversation_manager.add_to_watchlist_start(update, context)
        elif command == 'list':
            query.answer("Showing your series list...")
            return self.list_series_callback(update, context)
        elif command == 'watchlist':
            query.answer("Showing your watchlist...")
            return self.conversation_manager.view_watchlist_start(update, context)
        elif command == 'check':
            query.answer("Checking for updates...")
            return self.check_updates_callback(update, context)
        elif command == 'update':
            query.answer("Starting update series process...")
            return self.conversation_manager.update_series_start(update, context)
        elif command == 'remove':
            query.answer("Starting remove series process...")
            return self.conversation_manager.remove_series_start(update, context)
        elif command == 'help':
            query.answer("Showing help...")
            return self.help(update, context)
        elif command == 'addwatched':
            query.answer("Starting add watched series process...")
            return self.conversation_manager.add_watched_series_start(update, context)
        elif command == 'watched':
            query.answer("Showing your watched series...")
            return self.list_watched(update, context)
        
        # Fallback
        query.answer("Command not recognized")
        
    def list_series_callback(self, update: Update, context: CallbackContext) -> None:
        """List series from callback query"""
        query = update.callback_query
        user = self.db.get_user(query.from_user.id)
        
        if not user:
            # Create keyboard with options
            keyboard = [
                [InlineKeyboardButton("Add Series", callback_data="command_add")],
                [InlineKeyboardButton("View Watchlist", callback_data="command_watchlist")],
                [InlineKeyboardButton("Help", callback_data="command_help")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            query.edit_message_text(
                "You need to add a series first. Use the Add Series button or /add command.",
                reply_markup=reply_markup
            )
            return
            
        user_series_list = self.db.get_user_series_list(user.id)
        
        if not user_series_list:
            # Create keyboard with options
            keyboard = [
                [InlineKeyboardButton("Add Series", callback_data="command_add")],
                [InlineKeyboardButton("View Watchlist", callback_data="command_watchlist")],
                [InlineKeyboardButton("Help", callback_data="command_help")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            query.edit_message_text(
                "You're not watching any series yet. Use the Add Series button or /add command.",
                reply_markup=reply_markup
            )
            return
            
        # Edit current message to show header
        query.edit_message_text("*Your TV Series Watchlist:*", parse_mode=ParseMode.MARKDOWN)
        
        # Send each series as a separate message
        for user_series, series in user_series_list:
            year_str = f" ({series.year})" if series.year else ""
            message = f"• *{series.name}*{year_str}\n"
            message += f"  Currently at: Season {user_series.current_season}, Episode {user_series.current_episode}"
            
            # Create buttons for updating progress and marking as watched
            keyboard = [
                [
                    InlineKeyboardButton(f"📝 Update", callback_data=f"series_{series.tmdb_id}"),
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
        
        # Send footer with common actions
        keyboard = [
            [
                InlineKeyboardButton("➕ Add Series", callback_data="command_add"),
                InlineKeyboardButton("🔄 Check Updates", callback_data="command_check")
            ],
            [
                InlineKeyboardButton("📺 My Watchlist", callback_data="command_watchlist"),
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
        
    def check_updates_callback(self, update: Update, context: CallbackContext) -> None:
        """Check updates from callback query"""
        query = update.callback_query
        
        # Run a manual check
        result = self.scheduler.manual_check(query.from_user.id)
        
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
        
        query.edit_message_text(result, reply_markup=reply_markup)
        
    def move_to_watchlist(self, update: Update, context: CallbackContext) -> None:
        """Move a series from watching to watchlist"""
        query = update.callback_query
        query.answer()
        
        # Extract series ID from callback data
        series_id = int(query.data.split("_")[2])
        
        # Get user
        user = self.db.get_user(query.from_user.id)
        
        if not user:
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
            if series:
                # Create buttons for next actions
                keyboard = [
                    [
                        InlineKeyboardButton("View Watchlist", callback_data="command_watchlist"),
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
                [InlineKeyboardButton("View Watchlist", callback_data="command_watchlist")]
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
            InlineKeyboardButton("View Watchlist", callback_data="command_watchlist"),
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
                
                # Create buttons for next actions
                keyboard = [
                    [
                        InlineKeyboardButton("📺 View Watching", callback_data="command_list"),
                        InlineKeyboardButton("👁 View Watched", callback_data="command_watched")
                    ],
                    [
                        InlineKeyboardButton("➕ Add Series", callback_data="command_add"),
                        InlineKeyboardButton("❓ Help", callback_data="command_help")
                    ]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                query.edit_message_text(message, reply_markup=reply_markup)
            else:
                query.edit_message_text("Error marking series as watched. Please try again later.")
        except Exception as e:
            logger.error(f"Error marking series as watched: {e}", exc_info=True)
            query.edit_message_text("An error occurred while marking the series as watched. Please try again.")
        
def main():
    """Start the bot."""
    bot = SeriesTrackerBot()
    # Use webhook in production, polling in development
    use_webhook = os.getenv('ENVIRONMENT', 'production').lower() == 'production'
    bot.start_bot(use_webhook)
    
if __name__ == '__main__':
    main() 