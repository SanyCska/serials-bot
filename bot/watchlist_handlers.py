from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, ParseMode
from telegram.ext import CallbackContext, ConversationHandler, MessageHandler, Filters, CommandHandler, CallbackQueryHandler
import logging

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

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

class WatchlistHandlers:
    def __init__(self, db, tmdb):
        self.db = db
        self.tmdb = tmdb

    def add_series_start(self, update: Update, context: CallbackContext) -> int:
        """Start the add series conversation"""
        logger.info("Starting add series conversation")
        
        try:
            # Handle callback query case
            if update.callback_query:
                logger.info("Add series started from callback query")
                chat_id = update.callback_query.message.chat_id
                update.callback_query.answer()  # Answer the callback query to remove loading state
                context.bot.send_message(
                    chat_id=chat_id,
                    text="Пожалуйста, отправьте мне название сериала, который вы хотите добавить."
                )
            else:
                logger.info("Add series started from command")
                chat_id = update.message.chat_id
                context.bot.send_message(
                    chat_id=chat_id,
                    text="Пожалуйста, отправьте мне название сериала, который вы хотите добавить."
                )
            
            logger.info("Successfully sent initial message for add series")
            return SELECTING_SERIES
            
        except Exception as e:
            logger.error(f"Error in add_series_start: {e}", exc_info=True)
            try:
                if update.callback_query:
                    update.callback_query.answer("Error starting add series process")
                else:
                    update.message.reply_text("Error starting add series process. Please try again.")
            except Exception as e2:
                logger.error(f"Error sending error message: {e2}", exc_info=True)
            return ConversationHandler.END

    def series_selected(self, update: Update, context: CallbackContext) -> int:
        """Handle series selection"""
        query = update.callback_query
        logger.info(f"Series selection callback received: {query.data}")
        query.answer()

        if query.data == CANCEL_PATTERN:
            logger.info("Series selection cancelled")
            query.edit_message_text("Операция отменена.")
            return ConversationHandler.END

        # Check if this is a manual add request
        if query.data == MANUAL_ADD_PATTERN:
            logger.info("Manual add request received")
            query.edit_message_text(
                "Пожалуйста, введите точное название сериала, который вы хотите добавить:"
            )
            return MANUAL_SERIES_NAME

        # Extract series ID from callback data
        try:
            series_id = int(query.data.split("_")[1])
            logger.info(f"Processing series selection for ID: {series_id}")
        except (IndexError, ValueError) as e:
            logger.error(f"Error parsing series ID from callback data: {query.data}, error: {e}")
            query.edit_message_text("Error processing your selection. Please try again.")
            return ConversationHandler.END

        # Get series details from TMDB
        series_details = self.tmdb.get_series_details(series_id)

        # Always add the series to the local DB and add the user to the series (if not already present)
        user = self.db.add_user(
            query.from_user.id,
            query.from_user.username,
            query.from_user.first_name,
            query.from_user.last_name
        )
        if series_details:
            # Add series to DB
            local_series = self.db.add_series(
                series_details['id'],
                series_details['name'],
                series_details.get('year'),
                series_details.get('total_seasons')
            )
            # Add to user's watchlist or watching list depending on context
            if context.user_data.get('add_to_watchlist'):
                self.db.add_user_series(user.id, local_series.id, in_watchlist=True)
                context.user_data.pop('add_to_watchlist', None)
            else:
                self.db.add_user_series(user.id, local_series.id)
            # Use the local PK for all further steps
            series_id = local_series.id

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
            # Try to get from local DB (manual series)
            logger.warning(
                f"TMDB not found or no seasons for series ID: {series_id}, trying local DB for manual series.")
            local_series = self.db.get_series_by_id(series_id)
            if not local_series:
                logger.error(f"Failed to retrieve manual series details for ID: {series_id}")
                context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text="Ошибка получения данных о сериале. Пожалуйста, попробуйте позже"
                )
                return ConversationHandler.END
            # Use total_seasons from local DB
            total_seasons = getattr(local_series, 'total_seasons', 1)
            for season_num in range(1, total_seasons + 1):
                keyboard.append([
                    InlineKeyboardButton(
                        f"Сезон {season_num}",
                        callback_data=SEASON_PATTERN.format(series_id, season_num)
                    )
                ])
        # Add a manual season entry option
        keyboard.append([InlineKeyboardButton("Ввести номер сезона вручную",
                                              callback_data=MANUAL_SEASON_PATTERN.format(series_id))])
        # Add a cancel button
        keyboard.append([InlineKeyboardButton("Отмена", callback_data=CANCEL_PATTERN)])
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.edit_message_text(
            "Какой сезон вы сейчас смотрите?",
            reply_markup=reply_markup
        )
        # Save selected series_id for later steps
        context.user_data["selected_series_id"] = series_id
        return SELECTING_SEASON

    def manual_series_name_entered(self, update: Update, context: CallbackContext) -> int:
        """Handle manual series name entry"""
        series_name = update.message.text.strip()
        context.user_data["manual_series_name"] = series_name
        
        update.message.reply_text(
            "Введите год выхода сериала (например, 2020) или отправьте '0', если не знаете:"
        )
        return MANUAL_SERIES_YEAR

    def manual_series_year_entered(self, update: Update, context: CallbackContext) -> int:
        """Handle manual series year entry"""
        try:
            year_text = update.message.text.strip()
            if year_text == '0':
                year = None
            else:
                year = int(year_text)
                if year < 1900 or year > 2100:
                    update.message.reply_text("Пожалуйста, введите корректный год (между 1900 и 2100):")
                    return MANUAL_SERIES_YEAR
        except ValueError:
            update.message.reply_text("Пожалуйста, введите корректный год или '0':")
            return MANUAL_SERIES_YEAR
            
        context.user_data["manual_series_year"] = year
        
        update.message.reply_text(
            "Введите количество сезонов в сериале:"
        )
        return MANUAL_SERIES_SEASONS

    def manual_series_seasons_entered(self, update: Update, context: CallbackContext) -> int:
        """Handle manual series seasons entry"""
        try:
            seasons_text = update.message.text.strip()
            total_seasons = int(seasons_text)
            
            if total_seasons <= 0:
                update.message.reply_text("Number of seasons must be positive. Please enter a valid number:")
                return MANUAL_SERIES_SEASONS
                
            # Save the total seasons
            context.user_data["manual_series_seasons"] = total_seasons
            
            # Add the user to the database
            user = self.db.add_user(
                update.message.from_user.id,
                update.message.from_user.username,
                update.message.from_user.first_name,
                update.message.from_user.last_name
            )
            
            # Generate a unique negative ID for manual series (to avoid conflicts with TMDB IDs)
            manual_id = -1 * (abs(hash(context.user_data["manual_series_name"])) % 10000000)
            
            # Add series to database
            series = self.db.add_series(
                manual_id,
                context.user_data["manual_series_name"],
                context.user_data["manual_series_year"],
                context.user_data["manual_series_seasons"]
            )
            
            # Add to user's watchlist or watching list depending on context
            if context.user_data.get('add_to_watchlist'):
                self.db.add_user_series(user.id, series.id, in_watchlist=True)
                context.user_data.pop('add_to_watchlist', None)
            else:
                self.db.add_user_series(user.id, series.id)
            
            # Create keyboard for season selection
            keyboard = []
            for season in range(1, total_seasons + 1):
                keyboard.append([
                    InlineKeyboardButton(
                        f"Сезон {season}",
                        callback_data=SEASON_PATTERN.format(series.id, season)
                    )
                ])
            
            # Add cancel button
            keyboard.append([InlineKeyboardButton("Отмена", callback_data=CANCEL_PATTERN)])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            update.message.reply_text(
                "Какой сезон вы сейчас смотрите?",
                reply_markup=reply_markup
            )
            
            # Save selected series_id for later steps
            context.user_data["selected_series_id"] = series.id
            return SELECTING_SEASON
            
        except ValueError:
            update.message.reply_text("Пожалуйста, введите корректное число сезонов:")
            return MANUAL_SERIES_SEASONS

    def list_series(self, update: Update, context: CallbackContext) -> None:
        """List all TV series the user is watching."""
        logger.info(f"List command received from user {update.effective_user.id}")
        user = self.db.get_user(update.effective_user.id)
        
        if not user:
            logger.warning(f"User not found in database for telegram_id: {update.effective_user.id}")
            # Create keyboard with options
            keyboard = [
                [InlineKeyboardButton("Добавить сериал", callback_data="command_add")],
                [InlineKeyboardButton("Помощь", callback_data="command_help")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            if update.callback_query:
                update.callback_query.edit_message_text(
                    "Ваш список просматриваемых сериалов пуст",
                    reply_markup=reply_markup
                )
            else:
                update.message.reply_text(
                    "Ваш список просматриваемых сериалов пуст",
                    reply_markup=reply_markup
                )
            return
            
        user_series_list = self.db.get_user_series_list(user.id)
        logger.info(f"Retrieved {len(user_series_list) if user_series_list else 0} series for user {user.id}")
        
        if not user_series_list:
            logger.info(f"No series found for user {user.id}")
            # Create keyboard with options
            keyboard = [
                [InlineKeyboardButton("Добавить сериал", callback_data="command_add")],
                [InlineKeyboardButton("Помощь", callback_data="command_help")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            if update.callback_query:
                update.callback_query.edit_message_text(
                    "Вы еще не смотрите никаких сериалов. Используйте команду /addinwatchlist или кнопку ниже.",
                    reply_markup=reply_markup
                )
            else:
                update.message.reply_text(
                    "Вы еще не смотрите никаких сериалов. Используйте команду /addinwatchlist или кнопку ниже.",
                    reply_markup=reply_markup
                )
            return
            
        # Send header message
        try:
            if update.callback_query:
                update.callback_query.edit_message_text("*Ваш список просматриваемых сериалов:*", parse_mode=ParseMode.MARKDOWN)
                chat_id = update.callback_query.message.chat_id
            else:
                update.message.reply_text("*Ваш список просматриваемых сериалов:*", parse_mode=ParseMode.MARKDOWN)
                chat_id = update.message.chat_id
            logger.info("Sent header message")
        except Exception as e:
            logger.error(f"Error sending header message: {e}")
            return
        
        # Send each series as a separate message
        for user_series, series in user_series_list:
            try:
                year_str = f" ({series.year})" if series.year else ""
                message = f"• *{series.name}*{year_str}\n"
                message += f"  Сейчас: сезон {user_series.current_season}, серия {user_series.current_episode}"
                
                # Show the 'Watched' and 'Remove' buttons for each series
                keyboard = [
                    [
                        InlineKeyboardButton(f"✅ Просмотрено", callback_data=f"mark_watched_{series.id}")
                    ],
                    [
                        InlineKeyboardButton(f"❌ Удалить", callback_data=f"remove_series_{series.id}")
                    ]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                if update.callback_query:
                    context.bot.send_message(
                        chat_id=chat_id,
                        text=message,
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=reply_markup
                    )
                else:
                    update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
                logger.info(f"Sent message for series: {series.name}")
            except Exception as e:
                logger.error(f"Error sending message for series {series.name}: {e}")
        
        # Send footer with common actions
        try:
            keyboard = [
                [
                    InlineKeyboardButton("➕ Добавить сериал", callback_data="command_add"),
                    InlineKeyboardButton("📝 Обновить прогресс", callback_data="command_update")
                ],
                [
                    InlineKeyboardButton("❓ Помощь", callback_data="command_help"),
                    InlineKeyboardButton("Просмотренные сериалы", callback_data="command_watched")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            if update.callback_query:
                context.bot.send_message(
                    chat_id=chat_id,
                    text="*Действия:*",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=reply_markup
                )
            else:
                update.message.reply_text(
                    "*Действия:*",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=reply_markup
                )
            logger.info("Sent footer message with actions")
        except Exception as e:
            logger.error(f"Error sending footer message: {e}")

    def manual_series_name_prompt(self, update: Update, context: CallbackContext) -> int:
        """Prompt user to enter series name manually"""
        query = update.callback_query
        query.answer()
        query.edit_message_text(
            "Пожалуйста, введите точное название сериала, который вы хотите добавить:"
        )
        return MANUAL_SERIES_NAME

    def season_selected(self, update: Update, context: CallbackContext) -> int:
        """Handle season selection"""
        query = update.callback_query
        query.answer()

        if query.data == CANCEL_PATTERN:
            query.edit_message_text("Операция отменена.")
            return ConversationHandler.END

        # Extract series ID and season number from callback data
        try:
            _, series_id, season = query.data.split("_")
            series_id = int(series_id)
            season = int(season)
            logger.info(f"Processing season selection: series_id={series_id}, season={season}")
        except (IndexError, ValueError) as e:
            logger.error(f"Error parsing season data from callback: {query.data}, error: {e}")
            query.edit_message_text("Error processing your selection. Please try again.")
            return ConversationHandler.END

        # Save selected season
        context.user_data["selected_season"] = season

        # Get series details
        series = self.db.get_series_by_id(series_id)
        if not series:
            query.edit_message_text("Error: Series not found.")
            return ConversationHandler.END

        # Create keyboard for episode selection
        keyboard = []
        for episode in range(1, 21):  # Show up to 20 episodes
            keyboard.append([
                InlineKeyboardButton(
                    f"Серия {episode}",
                    callback_data=EPISODE_PATTERN.format(series_id, season, episode)
                )
            ])

        # Add manual episode entry option
        keyboard.append([
            InlineKeyboardButton(
                "Ввести серию вручную",
                callback_data=MANUAL_ENTRY_PATTERN.format(series_id, season)
            )
        ])

        # Add cancel button
        keyboard.append([InlineKeyboardButton("Отмена", callback_data=CANCEL_PATTERN)])

        reply_markup = InlineKeyboardMarkup(keyboard)

        query.edit_message_text(
            f"Какую серию сезона {season} вы сейчас смотрите?",
            reply_markup=reply_markup
        )

        return SELECTING_EPISODE

    def manual_season_entry(self, update: Update, context: CallbackContext) -> int:
        """Handle manual season entry"""
        if update.callback_query:
            query = update.callback_query
            query.answer()
            series_id = int(query.data.split("_")[2])
            query.edit_message_text(
                "Пожалуйста, введите номер сезона:"
            )
        else:
            try:
                season = int(update.message.text.strip())
                if season <= 0:
                    update.message.reply_text("Номер сезона должен быть положительным числом. Попробуйте еще раз:")
                    return MANUAL_SEASON_ENTRY
                
                series_id = context.user_data["selected_series_id"]
                context.user_data["selected_season"] = season
                
                # Create keyboard for episode selection
                keyboard = []
                for episode in range(1, 21):  # Show up to 20 episodes
                    keyboard.append([
                        InlineKeyboardButton(
                            f"Серия {episode}",
                            callback_data=EPISODE_PATTERN.format(series_id, season, episode)
                        )
                    ])

                # Add manual episode entry option
                keyboard.append([
                    InlineKeyboardButton(
                        "Ввести серию вручную",
                        callback_data=MANUAL_ENTRY_PATTERN.format(series_id, season)
                    )
                ])

                # Add cancel button
                keyboard.append([InlineKeyboardButton("Отмена", callback_data=CANCEL_PATTERN)])

                reply_markup = InlineKeyboardMarkup(keyboard)

                update.message.reply_text(
                    f"Какую серию сезона {season} вы сейчас смотрите?",
                    reply_markup=reply_markup
                )
                return SELECTING_EPISODE
                
            except ValueError:
                update.message.reply_text("Пожалуйста, введите корректный номер сезона:")
                return MANUAL_SEASON_ENTRY

        return MANUAL_SEASON_ENTRY

    def episode_selected(self, update: Update, context: CallbackContext) -> int:
        """Handle episode selection"""
        query = update.callback_query
        query.answer()

        if query.data == CANCEL_PATTERN:
            query.edit_message_text("Операция отменена.")
            return ConversationHandler.END

        # Extract series ID, season number, and episode number from callback data
        try:
            _, series_id, season, episode = query.data.split("_")
            series_id = int(series_id)
            season = int(season)
            episode = int(episode)
            logger.info(f"Processing episode selection: series_id={series_id}, season={season}, episode={episode}")
        except (IndexError, ValueError) as e:
            logger.error(f"Error parsing episode data from callback: {query.data}, error: {e}")
            query.edit_message_text("Error processing your selection. Please try again.")
            return ConversationHandler.END

        # Get user
        user = self.db.get_user(query.from_user.id)
        if not user:
            query.edit_message_text("Error: User not found.")
            return ConversationHandler.END

        # Update user's progress
        if self.db.update_user_series(user.id, series_id, season, episode):
            series = self.db.get_series_by_id(series_id)
            query.edit_message_text(
                f"Прогресс обновлен: {series.name}, сезон {season}, серия {episode}"
            )
        else:
            query.edit_message_text("Error updating progress. Please try again.")

        return ConversationHandler.END

    def manual_episode_entry(self, update: Update, context: CallbackContext) -> int:
        """Handle manual episode entry"""
        if update.callback_query:
            query = update.callback_query
            query.answer()
            series_id, season = query.data.split("_")[1:3]
            series_id = int(series_id)
            season = int(season)
            context.user_data["selected_series_id"] = series_id
            context.user_data["selected_season"] = season
            query.edit_message_text(
                "Пожалуйста, введите номер серии:"
            )
        else:
            try:
                episode = int(update.message.text.strip())
                if episode <= 0:
                    update.message.reply_text("Номер серии должен быть положительным числом. Попробуйте еще раз:")
                    return MANUAL_EPISODE_ENTRY
                
                series_id = context.user_data["selected_series_id"]
                season = context.user_data["selected_season"]
                
                # Get user
                user = self.db.get_user(update.message.from_user.id)
                if not user:
                    update.message.reply_text("Error: User not found.")
                    return ConversationHandler.END

                # Update user's progress
                if self.db.update_user_series(user.id, series_id, season, episode):
                    series = self.db.get_series_by_id(series_id)
                    update.message.reply_text(
                        f"Прогресс обновлен: {series.name}, сезон {season}, серия {episode}"
                    )
                else:
                    update.message.reply_text("Error updating progress. Please try again.")
                
                return ConversationHandler.END
                
            except ValueError:
                update.message.reply_text("Пожалуйста, введите корректный номер серии:")
                return MANUAL_EPISODE_ENTRY

        return MANUAL_EPISODE_ENTRY

    def mark_watched_callback(self, update: Update, context: CallbackContext) -> None:
        """Handle marking a series as watched."""
        query = update.callback_query
        query.answer()

        try:
            series_id = int(query.data.split('_')[2])
            user = self.db.get_user(query.from_user.id)

            if not user:
                query.edit_message_text("Ошибка: пользователь не найден.")
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
                message = f"✅ Я отметил '{series_name}' как просмотренный и переместил его в ваш список просмотренных!"

                query.edit_message_text(message)
            else:
                query.edit_message_text("Ошибка при отметке сериала как просмотренного. Пожалуйста, попробуйте позже.")
        except Exception as e:
            logger.error(f"Error marking series as watched: {e}", exc_info=True)
            query.edit_message_text(
                "Произошла ошибка при отметке сериала как просмотренного. Пожалуйста, попробуйте ещё раз.")

    def remove_series_callback(self, update: Update, context: CallbackContext) -> None:
        """Handle removing a series from the user's watching list."""
        query = update.callback_query
        query.answer()
        try:
            series_id = int(query.data.split('_')[2])
            user = self.db.get_user(query.from_user.id)
            if not user:
                query.edit_message_text("Ошибка: пользователь не найден.")
                return
            # Remove the series from user's watching list
            removed = self.db.remove_user_series(user.id, series_id)
            if removed:
                query.edit_message_text("✅ Сериал был удалён из вашего списка просмотра.")
            else:
                query.edit_message_text("❌ Не удалось удалить сериал. Пожалуйста, попробуйте позже.")
        except Exception as e:
            logger.error(f"Error removing series: {e}", exc_info=True)
            query.edit_message_text("Произошла ошибка при удалении сериала. Пожалуйста, попробуйте ещё раз.")

    def update_progress_start(self, update: Update, context: CallbackContext) -> int:
        """Start the update progress flow: show user's watching series as inline buttons."""
        user_id = update.effective_user.id if update.effective_user else update.callback_query.from_user.id
        user = self.db.get_user(user_id)
        if not user:
            if update.callback_query:
                update.callback_query.answer()
                update.callback_query.edit_message_text("Ваш список просматриваемых сериалов пуст")
            else:
                update.message.reply_text("Ваш список просматриваемых сериалов пуст")
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

    def get_add_series_conversation_handler(self, conversation_manager):
        """Create and return the add series ConversationHandler"""
        return ConversationHandler(
            entry_points=[
                CommandHandler("add", self.add_series_start),
                CommandHandler("addinwatchlist", self.add_series_start),
                CallbackQueryHandler(self.add_series_start, pattern="^command_add$")
            ],
            states={
                SELECTING_SERIES: [
                    MessageHandler(Filters.text & ~Filters.command, conversation_manager.search_series),
                    CallbackQueryHandler(self.series_selected, pattern=f"^{SERIES_PATTERN.format('.*')}$"),
                    CallbackQueryHandler(self.manual_series_name_prompt, pattern=f"^{MANUAL_ADD_PATTERN}$"),
                    CallbackQueryHandler(conversation_manager.cancel, pattern=f"^{CANCEL_PATTERN}$")
                ],
                MANUAL_SERIES_NAME: [
                    MessageHandler(Filters.text & ~Filters.command, self.manual_series_name_entered),
                    CommandHandler("cancel", conversation_manager.cancel)
                ],
                MANUAL_SERIES_YEAR: [
                    MessageHandler(Filters.text & ~Filters.command, self.manual_series_year_entered),
                    CommandHandler("cancel", conversation_manager.cancel)
                ],
                MANUAL_SERIES_SEASONS: [
                    MessageHandler(Filters.text & ~Filters.command, self.manual_series_seasons_entered),
                    CommandHandler("cancel", conversation_manager.cancel)
                ],
                SELECTING_SEASON: [
                    CallbackQueryHandler(self.season_selected, pattern=f"^{SEASON_PATTERN.format('.*', '.*')}$"),
                    CallbackQueryHandler(self.manual_season_entry, pattern=f"^{MANUAL_SEASON_PATTERN.format('.*')}$"),
                    CallbackQueryHandler(conversation_manager.cancel, pattern=f"^{CANCEL_PATTERN}$")
                ],
                MANUAL_SEASON_ENTRY: [
                    MessageHandler(Filters.text & ~Filters.command, self.manual_season_entry),
                    CommandHandler("cancel", conversation_manager.cancel)
                ],
                SELECTING_EPISODE: [
                    CallbackQueryHandler(self.episode_selected, pattern=f"^{EPISODE_PATTERN.format('.*', '.*', '.*')}$"),
                    CallbackQueryHandler(self.manual_episode_entry, pattern=f"^{MANUAL_ENTRY_PATTERN.format('.*', '.*')}$"),
                    CallbackQueryHandler(conversation_manager.cancel, pattern=f"^{CANCEL_PATTERN}$")
                ],
                MANUAL_EPISODE_ENTRY: [
                    MessageHandler(Filters.text & ~Filters.command, self.manual_episode_entry),
                    CommandHandler("cancel", conversation_manager.cancel)
                ]
            },
            fallbacks=[CommandHandler("cancel", conversation_manager.cancel)]
        )

    def get_update_progress_conversation_handler(self, conversation_manager):
        return ConversationHandler(
            entry_points=[
                CallbackQueryHandler(self.update_progress_start, pattern="^command_update$")
            ],
            states={
                SELECTING_SERIES: [
                    CallbackQueryHandler(self.update_progress_series_selected, pattern="^update_series_.*$"),
                    CallbackQueryHandler(conversation_manager.cancel, pattern=f"^{CANCEL_PATTERN}$")
                ],
                SELECTING_SEASON: [
                    CallbackQueryHandler(self.season_selected, pattern=f"^{SEASON_PATTERN.format('.*', '.*')}$"),
                    CallbackQueryHandler(self.manual_season_entry, pattern=f"^{MANUAL_SEASON_PATTERN.format('.*')}$"),
                    CallbackQueryHandler(conversation_manager.cancel, pattern=f"^{CANCEL_PATTERN}$")
                ],
                MANUAL_SEASON_ENTRY: [
                    MessageHandler(Filters.text & ~Filters.command, self.manual_season_entry),
                    CommandHandler("cancel", conversation_manager.cancel)
                ],
                SELECTING_EPISODE: [
                    CallbackQueryHandler(self.episode_selected, pattern=f"^{EPISODE_PATTERN.format('.*', '.*', '.*')}$"),
                    CallbackQueryHandler(self.manual_episode_entry, pattern=f"^{MANUAL_ENTRY_PATTERN.format('.*', '.*')}$"),
                    CallbackQueryHandler(conversation_manager.cancel, pattern=f"^{CANCEL_PATTERN}$")
                ],
                MANUAL_EPISODE_ENTRY: [
                    MessageHandler(Filters.text & ~Filters.command, self.manual_episode_entry),
                    CommandHandler("cancel", conversation_manager.cancel)
                ]
            },
            fallbacks=[CommandHandler("cancel", conversation_manager.cancel)]
        )
