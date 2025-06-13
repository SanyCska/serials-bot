from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, ParseMode
from telegram.ext import CallbackContext, ConversationHandler, MessageHandler, Filters
import logging

# Conversation states
SELECTING_SERIES, SELECTING_SEASON, SELECTING_EPISODE, MANUAL_EPISODE_ENTRY, MANUAL_SERIES_NAME, MANUAL_SERIES_YEAR, MANUAL_SERIES_SEASONS, SEARCH_WATCHED, SERIES_SELECTION, SELECT_SEASON, SELECT_EPISODE, MARK_WATCHED, MANUAL_SEASON_ENTRY = range(13)

# Callback data patterns
SERIES_PATTERN = "series_{}"
WATCHLIST_SERIES_PATTERN = "watchlist_series_{}"
SEASON_PATTERN = "season_{}_{}"  # series_id, season_number
EPISODE_PATTERN = "episode_{}_{}_{}"  # series_id, season_number, episode_number
MANUAL_ENTRY_PATTERN = "manual_{}_{}"  # series_id, season_number
MANUAL_ADD_PATTERN = "manual_add"
MANUAL_SEASON_PATTERN = "manual_season_{}"  # series_id
MOVE_TO_WATCHING = "move_watching_{}"  # series_id
MOVE_TO_WATCHLIST = "move_watchlist_{}"  # series_id
CANCEL_PATTERN = "cancel"

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class ConversationManager:
    """Manages conversation states for the bot."""
    def __init__(self, db, tmdb):
        """Initialize the conversation manager with database and TMDB API handlers."""
        self.db = db
        self.tmdb = tmdb

    # Common method ?
    def search_series(self, update: Update, context: CallbackContext, query=None, is_watched=False) -> int:
        """Search for TV series based on user input"""
        logger.info("Starting series search")
        
        if query is None:
            query = update.message.text.strip()
            logger.info(f"Search query from message: {query}")
            chat_id = update.message.chat_id
        else:
            logger.info(f"Search query from parameter: {query}")
            chat_id = update.effective_chat.id
        
        # Save the query in user_data
        context.user_data["series_query"] = query
        context.user_data["is_watched"] = is_watched
        
        # Search for TV series with the TMDB API
        results = self.tmdb.search_series(query)
        logger.info(f"Found {len(results) if results else 0} results for query: {query}")
        
        # Create inline keyboard with the results
        keyboard = []
        
        if results:
            for result in results:
                year_str = f" ({result['year']})" if result['year'] else ""
                keyboard.append([
                    InlineKeyboardButton(
                        f"{result['name']}{year_str}",
                        callback_data=SERIES_PATTERN.format(result['id'])
                    )
                ])
        
        # Add a manual add option
        keyboard.append([InlineKeyboardButton("Добавить вручную (нет в списке)", callback_data=MANUAL_ADD_PATTERN)])
            
        # Add a cancel button
        keyboard.append([InlineKeyboardButton("Отмена", callback_data=CANCEL_PATTERN)])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if not results:
            context.bot.send_message(
                chat_id=chat_id,
                text="Сериал с таким названием не найден. Хотите добавить его вручную?",
                reply_markup=reply_markup
            )
        else:
            context.bot.send_message(
                chat_id=chat_id,
                text="Вот сериалы, которые я нашел. Пожалуйста, выберите один или добавьте вручную:",
                reply_markup=reply_markup
            )
        
        return SELECTING_SERIES

    def cancel(self, update: Update, context: CallbackContext) -> int:
        """Cancel the conversation"""
        if update.message:
            update.message.reply_text("Операция отменена.")
        elif update.callback_query:
            query = update.callback_query
            query.answer()
            query.edit_message_text("Операция отменена.")
            
        # Clear user data
        context.user_data.clear()
        
        return ConversationHandler.END

    def update_progress_start(self, update: Update, context: CallbackContext) -> int:
        """Start the update progress flow: show user's watching series as inline buttons."""
        user_id = update.effective_user.id if update.effective_user else update.callback_query.from_user.id
        user = self.db.get_user(user_id)
        if not user:
            if update.callback_query:
                update.callback_query.answer()
                update.callback_query.edit_message_text("Сначала вам нужно добавить сериал. Используйте команду /add.")
            else:
                update.message.reply_text("Сначала вам нужно добавить сериал. Используйте команду /add.")
            return ConversationHandler.END
        user_series_list = self.db.get_user_series_list(user.id)
        if not user_series_list:
            if update.callback_query:
                update.callback_query.answer()
                update.callback_query.edit_message_text("Вы еще не смотрите никаких сериалов. Используйте команду /add.")
            else:
                update.message.reply_text("Вы еще не смотрите никаких сериалов. Используйте команду /add.")
            return ConversationHandler.END
        keyboard = []
        for user_series, series in user_series_list:
            year_str = f" ({series.year})" if series.year else ""
            keyboard.append([
                InlineKeyboardButton(
                    f"{series.name}{year_str}",
                    callback_data=f"update_series_{series.id}"
                )
            ])
        keyboard.append([InlineKeyboardButton("Отмена", callback_data=CANCEL_PATTERN)])
        reply_markup = InlineKeyboardMarkup(keyboard)
        if update.callback_query:
            update.callback_query.edit_message_text(
                "Выберите сериал для обновления прогресса:",
                reply_markup=reply_markup
            )
        else:
            update.message.reply_text(
                "Выберите сериал для обновления прогресса:",
                reply_markup=reply_markup
            )
        return SELECTING_SERIES

    def update_progress_series_selected(self, update: Update, context: CallbackContext) -> int:
        """Handle series selection for update progress flow, then prompt for season selection."""
        query = update.callback_query
        query.answer()
        try:
            series_id = int(query.data.split("_")[2])
            logger.info(f"Update progress: selected series ID: {series_id}")
        except (IndexError, ValueError) as e:
            logger.error(f"Error parsing series ID from update progress callback: {query.data}, error: {e}")
            query.edit_message_text("Ошибка при обработке вашего выбора. Попробуйте еще раз.")
            return ConversationHandler.END
        # Reuse the season selection logic from series_selected
        series_details = self.tmdb.get_series_details(series_id)
        keyboard = []
        if series_details and 'seasons' in series_details and series_details['seasons']:
            for season in series_details['seasons']:
                keyboard.append([
                    InlineKeyboardButton(
                        f"Сезон {season['season_number']}",
                        callback_data=SEASON_PATTERN.format(series_id, season['season_number'])
                    )
                ])
        else:
            local_series = self.db.get_series_by_id(series_id)
            if not local_series:
                query.edit_message_text("Ошибка получения данных о сериале. Пожалуйста, попробуйте позже")
                return ConversationHandler.END
            total_seasons = getattr(local_series, 'total_seasons', 1)
            for season_num in range(1, total_seasons + 1):
                keyboard.append([
                    InlineKeyboardButton(
                        f"Сезон {season_num}",
                        callback_data=SEASON_PATTERN.format(series_id, season_num)
                    )
                ])
        keyboard.append([InlineKeyboardButton("Ввести номер сезона вручную", callback_data=MANUAL_SEASON_PATTERN.format(series_id))])
        keyboard.append([InlineKeyboardButton("Отмена", callback_data=CANCEL_PATTERN)])
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.edit_message_text(
            "Какой сезон вы сейчас смотрите?",
            reply_markup=reply_markup
        )
        context.user_data["selected_series_id"] = series_id
        return SELECTING_SEASON 

    def search_watchlist_series(self, update: Update, context: CallbackContext) -> int:
        """Search for a series to add to the watch later list."""
        return self.search_series(update, context, query=update.message.text, is_watched=False) 