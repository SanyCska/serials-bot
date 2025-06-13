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

    def watchlater_series_selected(self, update: Update, context: CallbackContext) -> int:
        """Handle series selection for watch later list only."""
        query = update.callback_query
        query.answer()

        series_id = int(query.data.split('_')[1])
        user = self.db.get_user(update.effective_user.id)

        if not user:
            query.edit_message_text("Ошибка: пользователь не найден.")
            return ConversationHandler.END

        # Get series details from TMDB
        series_details = self.tmdb.get_series_details(series_id)
        if not series_details:
            query.edit_message_text('Извините, я не смог найти этот сериал.')
            return ConversationHandler.END

        # Add series to DB
        local_series = self.db.add_series(
            series_details['id'],
            series_details['name'],
            series_details.get('year'),
            series_details.get('total_seasons')
        )

        # Add to user's watch later list
        self.db.add_user_series(user.id, local_series.id, in_watchlist=True)
        query.edit_message_text(
            f'"{local_series.name}" добавлен в список "Посмотреть позже"'
        )
        return ConversationHandler.END
        
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

    # По ходу это для просмотренных
    def handle_watchlist_actions(self, update: Update, context: CallbackContext) -> int:
        """Handle watchlist actions - move to watching or remove"""
        query = update.callback_query
        logger.info(f"Received watchlist action: {query.data}")
        query.answer()
        
        # Check if moving to watching list
        if query.data.startswith("move_watching_"):
            logger.info("Processing move to watching action")
            series_id = int(query.data.split("_")[2])
            logger.info(f"Extracted series_id: {series_id}")
            
            user = self.db.get_user(query.from_user.id)
            if not user:
                logger.error(f"User not found for telegram_id: {query.from_user.id}")
                query.edit_message_text("Ошибка: пользователь не найден.")
                return ConversationHandler.END
                
            logger.info(f"Found user with id: {user.id}")
            series = None
            
            # Get series name for the message
            user_series_list = self.db.get_user_series_list(user.id, watchlist_only=True)
            logger.info(f"Found {len(user_series_list)} series in watchlist")
            for user_series, s in user_series_list:
                logger.info(f"Checking series: id={s.id}, name={s.name}")
                if s.id == series_id:
                    series = s
                    logger.info(f"Found matching series: {series.name}")
                    break
                    
            # Move series from watchlist to watching
            logger.info(f"Calling move_to_watching for user_id={user.id}, series_id={series_id}")
            move_result = self.db.move_to_watching(user.id, series_id)
            logger.info(f"Move result: {move_result}")
            
            if move_result:
                if series:
                    series_name = series.name
                    query.edit_message_text(
                        f"✅ Сериал '{series_name}' теперь в процессе просмотра!\n\n"
                    )
                else:
                    query.edit_message_text("✅ Сериал теперь в процессе просмотра!")
            else:
                logger.error(f"Failed to move series {series_id} to watching for user {user.id}")
                query.edit_message_text("Ошибка при перемещении сериала. Попробуйте позже.")
                
            return ConversationHandler.END
        
        # Check if this is a remove request
        if query.data.startswith("watchlist_series_"):
            logger.info("Processing watchlist removal action")
            try:
                series_id = int(query.data.split("_")[2])
                logger.info(f"Attempting to remove series_id: {series_id}")
                user = self.db.get_user(query.from_user.id)
                
                if not user:
                    logger.error(f"User not found for telegram_id: {query.from_user.id}")
                    query.edit_message_text("Ошибка: пользователь не найден.")
                    return ConversationHandler.END
                
                logger.info(f"Found user with id: {user.id}")
                
                # Get series name for the success message
                user_series_list = self.db.get_user_series_list(user.id, watchlist_only=True)
                series_name = None
                for user_series, s in user_series_list:
                    if s.id == series_id:
                        series_name = s.name
                        break
                
                logger.info(f"Found series name: {series_name}")
                
                # Remove the series from user's watchlist
                removal_success = self.db.remove_user_series(user.id, series_id)
                logger.info(f"Removal success: {removal_success}")
                
                if removal_success:
                    message = f"Я удалил '{series_name}' из вашего списка для просмотра." if series_name else "Сериал удален из вашего списка для просмотра."
                    
                    # Show updated watchlist
                    updated_watchlist = self.db.get_user_series_list(user.id, watchlist_only=True)
                    if updated_watchlist:
                        message += "\n\nТвой обновленный список просмотренных сериалов: "
                        for _, s in updated_watchlist:
                            message += f"\n• {s.name}"
                    else:
                        message += "\n\nВаш список для просмотра теперь пуст."
                    
                    logger.info(f"Sending success message: {message}")
                    query.edit_message_text(message)
                else:
                    logger.error(f"Failed to remove series {series_id} for user {user.id}")
                    query.edit_message_text("Ошибка при удалении сериала. Попробуйте позже.")
            except Exception as e:
                logger.error(f"Error in watchlist removal: {e}", exc_info=True)
                query.edit_message_text("Произошла ошибка при удалении сериала. Попробуйте еще раз.")
                
            return ConversationHandler.END

    def mark_watched_start(self, update: Update, context: CallbackContext) -> int:
        """Start the process of marking a series as watched."""
        user_id = update.effective_user.id
        series_list = self.db.get_user_series_list(user_id)
        
        if not series_list:
            update.message.reply_text("У вас нет сериалов в списке.")
            return ConversationHandler.END
        
        keyboard = []
        for series in series_list:
            if not series.is_watched:  # Only show unwatched series
                keyboard.append([InlineKeyboardButton(
                    series.title,
                    callback_data=f"watched_{series.series_id}"
                )])
        
        if not keyboard:
            update.message.reply_text("У вас нет непросмотренных сериалов.")
            return ConversationHandler.END
        
        keyboard.append([InlineKeyboardButton("Отмена", callback_data="cancel")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        update.message.reply_text(
            "Выберите сериал, чтобы отметить как просмотренный:",
            reply_markup=reply_markup
        )
        return self.MARK_WATCHED

    def mark_watched_selected(self, update: Update, context: CallbackContext) -> int:
        """Handle the selection of a series to mark as watched."""
        query = update.callback_query
        query.answer()
        
        if query.data == "cancel":
            query.edit_message_text("Операция отменена.")
            return ConversationHandler.END
        
        series_id = int(query.data.split("_")[1])
        user_id = update.effective_user.id
        
        if self.db.mark_as_watched(user_id, series_id):
            series = self.db.get_series(series_id)
            query.edit_message_text(f"✅ Отметил '{series.title}' как просмотренный!")
        else:
            query.edit_message_text("❌ Не удалось отметить сериал как просмотренный.")
        
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