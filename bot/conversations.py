from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, ParseMode
from telegram.ext import CallbackContext, ConversationHandler, MessageHandler, Filters
import logging
import random

from bot.database.db_handler import DBHandler
from bot.tmdb_api import TMDBApi

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
    def __init__(self):
        self.db = DBHandler()
        self.tmdb = TMDBApi()
        
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
            logger.warning(f"TMDB not found or no seasons for series ID: {series_id}, trying local DB for manual series.")
            local_series = self.db.get_series_by_id(series_id)
            if not local_series:
                logger.error(f"Failed to retrieve manual series details for ID: {series_id}")
                context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text="Error retrieving series details. Please try again later."
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
        keyboard.append([InlineKeyboardButton("Ввести номер сезона вручную", callback_data=MANUAL_SEASON_PATTERN.format(series_id))])
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

    def season_selected(self, update: Update, context: CallbackContext) -> int:
        """Handle season selection"""
        query = update.callback_query
        logger.info(f"Season selection callback received: {query.data}")
        query.answer()
        
        if query.data == CANCEL_PATTERN:
            logger.info("Season selection cancelled")
            context.bot.send_message(
                chat_id=query.message.chat_id,
                text="Operation cancelled."
            )
            return ConversationHandler.END
            
        # Check if this is a manual season entry request
        if query.data.startswith("manual_season_"):
            try:
                series_id = int(query.data.split("_")[2])
                logger.info(f"Manual season entry requested for series ID: {series_id}")
                context.user_data["selected_series_id"] = series_id
                context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text="Please enter the season number you're currently watching:"
                )
                return MANUAL_SEASON_ENTRY
            except (IndexError, ValueError) as e:
                logger.error(f"Error parsing series ID from manual season callback: {query.data}, error: {e}")
                context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text="Error processing your request. Please try again."
                )
                return ConversationHandler.END
        
        # Extract series ID and season number from callback data
        try:
            _, series_id, season_number = query.data.split("_")
            series_id = int(series_id)
            season_number = int(season_number)
            logger.info(f"Processing season selection for series ID: {series_id}, season: {season_number}")
        except (IndexError, ValueError) as e:
            logger.error(f"Error parsing season data from callback: {query.data}, error: {e}")
            context.bot.send_message(
                chat_id=query.message.chat_id,
                text="Error processing your selection. Please try again."
            )
            return ConversationHandler.END
        
        # Save the season number in user_data
        context.user_data["selected_season"] = {
            "season_number": season_number,
            "episodes": []
        }
        context.user_data["selected_series_id"] = series_id
        # Prompt user to enter episode number as a message
        context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"Введите номер серии:"
        )
        return MANUAL_EPISODE_ENTRY

    def manual_season_entry(self, update: Update, context: CallbackContext) -> int:
        """Handle manual season number entry"""
        try:
            # Handle both callback query and message cases
            if update.callback_query:
                # This is the initial callback when user clicks "Enter season number manually"
                query = update.callback_query
                logger.info(f"Manual season entry requested with callback data: {query.data}")
                
                try:
                    series_id = int(query.data.split("_")[2])
                    logger.info(f"Manual season entry requested for series ID: {series_id}")
                    context.user_data["selected_series_id"] = series_id
                    query.edit_message_text(
                        "Please enter the season number you're currently watching:"
                    )
                    return MANUAL_SEASON_ENTRY
                except (IndexError, ValueError) as e:
                    logger.error(f"Error parsing series ID from manual season callback: {query.data}, error: {e}")
                    query.edit_message_text("Error processing your request. Please try again.")
                    return ConversationHandler.END
            else:
                # This is when user enters the season number
                try:
                    season_number = int(update.message.text.strip())
                    if season_number <= 0:
                        update.message.reply_text(
                            "Please enter a positive season number or use /cancel to cancel."
                        )
                        return MANUAL_SEASON_ENTRY
                except ValueError:
                    update.message.reply_text(
                        "Please enter a valid number for the season or use /cancel to cancel."
                    )
                    return MANUAL_SEASON_ENTRY

                series_id = context.user_data.get("selected_series_id")
                
                if not series_id:
                    update.message.reply_text("Error: Series information not found. Please try again.")
                    return ConversationHandler.END
                    
                # Get series details from TMDB
                series_details = self.tmdb.get_series_details(series_id)
                
                if not series_details:
                    update.message.reply_text("Error retrieving series details. Please try again later.")
                    return ConversationHandler.END

                # Save the season number in user_data
                context.user_data["selected_season"] = {
                    "season_number": season_number,
                    "episodes": []  # Empty list since we don't have episode data
                }
                
                # Directly prompt for episode number
                update.message.reply_text(
                    f"Пожалуйста, введите номер серии для сезона {season_number}, который вы сейчас смотрите:"
                )
                
                return MANUAL_EPISODE_ENTRY
                
        except Exception as e:
            logger.error(f"Error in manual season entry: {e}", exc_info=True)
            if update.callback_query:
                update.callback_query.edit_message_text(
                    "An error occurred. Please try again or use /cancel to cancel."
                )
            else:
                update.message.reply_text(
                    "An error occurred. Please try again or use /cancel to cancel."
                )
            return MANUAL_SEASON_ENTRY

    def episode_selected(self, update: Update, context: CallbackContext) -> int:
        """Handle episode selection"""
        query = update.callback_query
        logger.info(f"Episode selection callback received: {query.data}")
        query.answer()
        
        if query.data == CANCEL_PATTERN:
            logger.info("Episode selection cancelled")
            context.bot.send_message(
                chat_id=query.message.chat_id,
                text="Episode selection cancelled. The series has been added to your watchlist."
            )
            return ConversationHandler.END
            
        # Check if this is a manual entry request
        if query.data.startswith("manual_"):
            try:
                # Format is manual_series_id_season_number
                data_parts = query.data.split("_")
                if len(data_parts) != 3:
                    logger.error(f"Invalid manual entry callback format: {query.data}")
                    context.bot.send_message(
                        chat_id=query.message.chat_id,
                        text="Error processing your request. Please try again."
                    )
                    return ConversationHandler.END
                    
                series_id = int(data_parts[1])
                season_number = int(data_parts[2])
                logger.info(f"Manual episode entry requested for series ID: {series_id}, season: {season_number}")
                context.user_data["selected_series_id"] = series_id
                context.user_data["selected_season"] = season_number
                
                context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=f"Пожалуйста, введите номер серии для сезона {season_number}, который вы сейчас смотрите:"
                )
                
                return MANUAL_EPISODE_ENTRY
            except (IndexError, ValueError) as e:
                logger.error(f"Error parsing manual episode entry data: {query.data}, error: {e}")
                context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text="Error processing your request. Please try again."
                )
                return ConversationHandler.END
            
        # Extract series_id, season_number, and episode_number from callback data
        try:
            _, series_id, season_number, episode_number = query.data.split("_")
            series_id = int(series_id)
            season_number = int(season_number)
            episode_number = int(episode_number)
            logger.info(f"Processing episode selection for series ID: {series_id}, season: {season_number}, episode: {episode_number}")
        except (IndexError, ValueError) as e:
            logger.error(f"Error parsing episode data from callback: {query.data}, error: {e}")
            context.bot.send_message(
                chat_id=query.message.chat_id,
                text="Error processing your selection. Please try again."
            )
            return ConversationHandler.END
        
        # Update user's progress
        user = self.db.get_user(query.from_user.id)
        series = self.db.get_series_by_id(series_id)
        
        if user and series:
            logger.info(f"Updating progress for user {user.id}, series {series.name} to S{season_number}E{episode_number}")
            self.db.update_user_series(user.id, series.id, season_number, episode_number)
            
            context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"Отлично! Я обновил ваш прогресс до Сезона {season_number}, Серии {episode_number}."
            )
        else:
            logger.error(f"Failed to update progress - user or series not found. User: {user}, Series: {series}")
            context.bot.send_message(
                chat_id=query.message.chat_id,
                text="Ошибка обновления прогресса. Пожалуйста, попробуйте позже."
            )
            
        return ConversationHandler.END

    def manual_episode_entry(self, update: Update, context: CallbackContext) -> int:
        """Handle manual episode number entry (now always used after season selection)"""
        logger.info("Manual episode entry handler called")
        try:
            # Only handle message case (no callback)
            logger.info(f"User data: {context.user_data}")
            try:
                episode_number = int(update.message.text.strip())
                if episode_number <= 0:
                    update.message.reply_text(
                        "Пожалуйста, введите положительный номер серии или используйте /cancel для отмены."
                    )
                    return MANUAL_EPISODE_ENTRY
            except ValueError:
                update.message.reply_text(
                    "Пожалуйста, введите корректный номер серии или используйте /cancel для отмены."
                )
                return MANUAL_EPISODE_ENTRY
            series_id = context.user_data.get("selected_series_id")
            season_data = context.user_data.get("selected_season", {})
            season_number = season_data.get("season_number")
            logger.info(f"Processing manual episode entry - Series ID: {series_id}, Season: {season_number}, Episode: {episode_number}")
            if not series_id or not season_number:
                logger.error(f"Missing series_id or season_number in context: {context.user_data}")
                update.message.reply_text("Error: Series or season information not found. Please try again from the beginning.")
                return ConversationHandler.END
            user = self.db.get_user(update.message.from_user.id)
            series = self.db.get_series_by_id(int(series_id))
            if user and series:
                logger.info(f"Updating progress for user {user.id}, series {series.name} to S{season_number}E{episode_number}")
                self.db.update_user_series(user.id, series.id, season_number, episode_number)
                update.message.reply_text(
                    f"Отлично! Я обновил ваш прогресс до Сезона {season_number}, Серии {episode_number}."
                )
            else:
                logger.error(f"Failed to update progress - user or series not found. User: {user}, Series: {series}")
                update.message.reply_text("Ошибка обновления прогресса. Пожалуйста, попробуйте позже.")
            return ConversationHandler.END
        except Exception as e:
            logger.error(f"Error in manual episode entry: {e}", exc_info=True)
            update.message.reply_text(
                "Произошла ошибка. Пожалуйста, попробуйте снова или используйте /cancel для отмены."
            )
            return MANUAL_EPISODE_ENTRY
        
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

    def add_to_watchlist_start(self, update: Update, context: CallbackContext) -> int:
        """Start the add to watchlist conversation"""
        # Handle callback query case
        if update.callback_query:
            update.callback_query.edit_message_text(
                "Пожалуйста, отправьте мне название сериала, который вы хотите добавить в список 'Посмотреть позже'."
            )
        else:
            update.message.reply_text(
                "Пожалуйста, отправьте мне название сериала, который вы хотите добавить в список 'Посмотреть позже'."
            )
        
        # Set flag to indicate watchlist operation
        context.user_data["add_to_watchlist"] = True
        
        return SELECTING_SERIES
    
    def view_watchlist_start(self, update: Update, context: CallbackContext) -> int:
        """Start the watchlist viewing process."""
        # Get user from database
        user = self.db.get_user(update.effective_user.id if update.effective_user else update.callback_query.from_user.id)
        
        if not user:
            message = "Сначала вам нужно добавить сериал. Используйте команду /add или /addwatch."
            if update.callback_query:
                update.callback_query.answer()
                update.callback_query.edit_message_text(message)
            else:
                update.message.reply_text(message)
            return ConversationHandler.END
            
        # Get user's watchlist
        user_series_list = self.db.get_user_series_list(user.id, watchlist_only=True)
        
        if not user_series_list:
            # Create keyboard with options
            keyboard = [
                [InlineKeyboardButton("Добавить в список 'Посмотреть позже'", callback_data="command_addwatch")],
                [InlineKeyboardButton("Просмотр списка просмотра", callback_data="command_list")],
                [InlineKeyboardButton("Помощь", callback_data="command_help")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            message = "Ваш список 'Посмотреть позже' пуст. Используйте /addinwatchlater для добавления сериалов, которые планируете посмотреть."
            if update.callback_query:
                update.callback_query.answer()
                update.callback_query.edit_message_text(message, reply_markup=reply_markup)
            else:
                update.message.reply_text(message, reply_markup=reply_markup)
            return ConversationHandler.END
            
        # Send header message
        if update.callback_query:
            update.callback_query.answer()
            update.callback_query.edit_message_text("*Ваш список 'Посмотреть позже':*", parse_mode=ParseMode.MARKDOWN)
            chat_id = update.callback_query.message.chat_id
        else:
            update.message.reply_text("*Ваш список 'Посмотреть позже':*", parse_mode=ParseMode.MARKDOWN)
            chat_id = update.message.chat_id
            
        # Send each series as a separate message
        for user_series, series in user_series_list:
            year_str = f" ({series.year})" if series.year else ""
            message = f"• *{series.name}*{year_str}"
            
            # Create buttons specific to this series
            keyboard = [
                [
                    InlineKeyboardButton(f"▶️ Начать просмотр", callback_data=f"move_watching_{series.id}"),
                    InlineKeyboardButton(f"❌ Удалить", callback_data=f"watchlist_series_{series.id}")
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
                update.message.reply_text(
                    message,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=reply_markup
                )
        
        # Send footer with common actions
        keyboard = [
            [
                InlineKeyboardButton("➕ Добавить в список", callback_data="command_addwatch"),
                InlineKeyboardButton("📺 Просмотр списка", callback_data="command_list")
            ],
            [
                InlineKeyboardButton("❓ Помощь", callback_data="command_help")
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
            
        return SELECTING_SERIES
    
    def handle_watchlist_actions(self, update: Update, context: CallbackContext) -> int:
        """Handle watchlist actions - move to watching or remove"""
        query = update.callback_query
        logger.info(f"Received watchlist action: {query.data}")
        query.answer()
        
        # Check if moving to watching list
        if query.data.startswith("move_watching_"):
            logger.info("Processing move to watching action")
            series_id = int(query.data.split("_")[2])
            user = self.db.get_user(query.from_user.id)
            series = None
            
            # Get series name for the message
            user_series_list = self.db.get_user_series_list(user.id, watchlist_only=True)
            for user_series, s in user_series_list:
                if s.id == series_id:
                    series = s
                    break
                    
            # Move series from watchlist to watching
            if self.db.move_to_watching(user.id, series_id):
                if series:
                    series_name = series.name
                    # Send prompt to update current episode and season
                    keyboard = []
                    
                    # Get series seasons from TMDB if not manually added
                    if series.tmdb_id > 0:
                        series_details = self.tmdb.get_series_details(series.tmdb_id)
                        if series_details and series_details['seasons']:
                            for season in series_details['seasons']:
                                keyboard.append([
                                    InlineKeyboardButton(
                                        f"Сезон {season['season_number']}",
                                        callback_data=SEASON_PATTERN.format(series.tmdb_id, season['season_number'])
                                    )
                                ])
                    
                    # If no seasons from TMDB or manually added series, create buttons for seasons
                    if not keyboard and series.total_seasons:
                        for season_num in range(1, series.total_seasons + 1):
                            keyboard.append([
                                InlineKeyboardButton(
                                    f"Сезон {season_num}",
                                    callback_data=SEASON_PATTERN.format(series.id, season_num)
                                )
                            ])
                    
                    # Add cancel button
                    keyboard.append([InlineKeyboardButton("Отмена", callback_data=CANCEL_PATTERN)])
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    query.edit_message_text(
                        f"I've moved '{series_name}' to your watching list!\n\n"
                        "Какой сезон вы сейчас смотрите?",
                        reply_markup=reply_markup
                    )
                    
                    context.user_data["selected_series_id"] = series.id
                    return SELECTING_SEASON
                else:
                    query.edit_message_text("Series has been moved to your watching list.")
            else:
                query.edit_message_text("Error moving series. Please try again later.")
                
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
                    query.edit_message_text("Error: User not found.")
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
                    message = f"I've removed '{series_name}' from your watchlist." if series_name else "Series has been removed from your watchlist."
                    
                    # Show updated watchlist
                    updated_watchlist = self.db.get_user_series_list(user.id, watchlist_only=True)
                    if updated_watchlist:
                        message += "\n\nYour updated watchlist:"
                        for _, s in updated_watchlist:
                            message += f"\n• {s.name}"
                    else:
                        message += "\n\nYour watchlist is now empty."
                    
                    logger.info(f"Sending success message: {message}")
                    query.edit_message_text(message)
                else:
                    logger.error(f"Failed to remove series {series_id} for user {user.id}")
                    query.edit_message_text("Error removing series. Please try again later.")
            except Exception as e:
                logger.error(f"Error in watchlist removal: {e}", exc_info=True)
                query.edit_message_text("An error occurred while removing the series. Please try again.")
                
            return ConversationHandler.END

    def add_watched_series_start(self, update: Update, context: CallbackContext) -> int:
        """Start the conversation to add a watched series."""
        # Set the context to indicate this is for adding a watched series
        context.user_data["is_watched"] = True

        # If called from a callback button
        if update.callback_query:
            chat_id = update.callback_query.message.chat_id
            update.callback_query.answer()
            context.bot.send_message(
                chat_id=chat_id,
                text='Пожалуйста, отправьте мне название сериала, который вы уже посмотрели:'
            )
            return SEARCH_WATCHED

        # If called from a command
        # Check if there's text after the command
        query = update.message.text.replace('/addwatched', '').strip()
        if query:
            # If there's text after the command, go directly to search
            return self.search_series(update, context, query=query, is_watched=True)

        # If no text after command, ask for series name
        update.message.reply_text(
            'Пожалуйста, отправьте мне название сериала, который вы уже посмотрели:'
        )
        return SEARCH_WATCHED
        
    def search_watched_series(self, update: Update, context: CallbackContext) -> int:
        """Search for a series to mark as watched."""
        logger.info("Searching for watched series")
        return self.search_series(update, context, query=update.message.text, is_watched=True)
        
    def watched_series_selected(self, update: Update, context: CallbackContext) -> int:
        query = update.callback_query
        query.answer()

        series_id = int(query.data.split('_')[1])
        user = self.db.get_user(update.effective_user.id)

        if not user:
            query.edit_message_text("Error: User not found.")
            return ConversationHandler.END

        # 1. Получить детали сериала
        series_details = self.tmdb.get_series_details(series_id)
        if not series_details:
            query.edit_message_text('Sorry, I could not find that series.')
            return ConversationHandler.END

        # 2. Добавить сериал в таблицу series (или получить его)
        local_series = self.db.add_series(
            series_details['id'],
            series_details['name'],
            series_details.get('year'),
            series_details.get('total_seasons')
        )

        # 3. Добавить в user_series с использованием local_series.id
        self.db.add_watched_series(user.id, local_series.id)

        query.edit_message_text(
            f'"{local_series.name}" добавлен в список просмотренных сериалов'
        )
        return ConversationHandler.END

    def mark_watched_start(self, update: Update, context: CallbackContext) -> int:
        """Start the process of marking a series as watched."""
        user_id = update.effective_user.id
        series_list = self.db.get_user_series_list(user_id)
        
        if not series_list:
            update.message.reply_text("You don't have any series in your list.")
            return ConversationHandler.END
        
        keyboard = []
        for series in series_list:
            if not series.is_watched:  # Only show unwatched series
                keyboard.append([InlineKeyboardButton(
                    series.title,
                    callback_data=f"watched_{series.series_id}"
                )])
        
        if not keyboard:
            update.message.reply_text("You don't have any unwatched series.")
            return ConversationHandler.END
        
        keyboard.append([InlineKeyboardButton("Отмена", callback_data="cancel")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        update.message.reply_text(
            "Select a series to mark as watched:",
            reply_markup=reply_markup
        )
        return self.MARK_WATCHED

    def mark_watched_selected(self, update: Update, context: CallbackContext) -> int:
        """Handle the selection of a series to mark as watched."""
        query = update.callback_query
        query.answer()
        
        if query.data == "cancel":
            query.edit_message_text("Operation cancelled.")
            return ConversationHandler.END
        
        series_id = int(query.data.split("_")[1])
        user_id = update.effective_user.id
        
        if self.db.mark_as_watched(user_id, series_id):
            series = self.db.get_series(series_id)
            query.edit_message_text(f"✅ Marked '{series.title}' as watched!")
        else:
            query.edit_message_text("❌ Failed to mark series as watched.")
        
        return ConversationHandler.END 

    def manual_series_name_entered(self, update: Update, context: CallbackContext) -> int:
        """Handle manual series name entry"""
        series_name = update.message.text.strip()
        
        if not series_name:
            update.message.reply_text("Пожалуйста, введите корректное название сериала или используйте /cancel для отмены.")
            return MANUAL_SERIES_NAME
        
        # Save the series name
        context.user_data["manual_series_name"] = series_name
        
        update.message.reply_text(
            "Пожалуйста, введите год начала сериала (например, 2020) или 0, если неизвестно:"
        )
        
        return MANUAL_SERIES_YEAR 

    def manual_series_year_entered(self, update: Update, context: CallbackContext) -> int:
        """Handle manual series year entry"""
        try:
            year_text = update.message.text.strip()
            year = int(year_text)
            
            if year < 0:
                update.message.reply_text("Год не может быть отрицательным. Пожалуйста, введите корректный год или 0, если неизвестно:")
                return MANUAL_SERIES_YEAR
                
            # Save the year (or None if 0)
            context.user_data["manual_series_year"] = year if year > 0 else None
            
            update.message.reply_text(
                "Пожалуйста, введите общее количество сезонов (или приблизительное число):"
            )
            
            return MANUAL_SERIES_SEASONS
            
        except ValueError:
            update.message.reply_text("Please enter a valid number for the year or use /cancel to cancel.")
            return MANUAL_SERIES_YEAR 

    def manual_series_name_prompt(self, update: Update, context: CallbackContext) -> int:
        """Prompt user to enter the series name manually after clicking 'Add manually' button, or use the previously entered name if available."""
        # Try to use the name the user already entered
        prev_name = context.user_data.get("series_query")
        if prev_name:
            context.user_data["manual_series_name"] = prev_name
            update.callback_query.answer()
            update.callback_query.edit_message_text(
                "Пожалуйста, введите год начала сериала (например, 2020) или 0, если неизвестно:"
            )
            return MANUAL_SERIES_YEAR
        # Otherwise, ask for the name
        query = update.callback_query
        query.answer()
        query.edit_message_text("Please enter the exact name of the TV series you want to add:")
        return MANUAL_SERIES_NAME

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
            for season_num in range(1, total_seasons + 1):
                keyboard.append([
                    InlineKeyboardButton(
                        f"Сезон {season_num}",
                        callback_data=SEASON_PATTERN.format(series.id, season_num)
                    )
                ])
                
            # Add a cancel button
            keyboard.append([InlineKeyboardButton("Отмена", callback_data=CANCEL_PATTERN)])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            update.message.reply_text(
                f"Я добавил '{context.user_data['manual_series_name']}' в ваш список!\n\n"
                "Какой сезон вы сейчас смотрите?",
                reply_markup=reply_markup
            )
            
            return SELECTING_SEASON
            
        except ValueError:
            update.message.reply_text("Please enter a valid number for the seasons or use /cancel to cancel.")
            return MANUAL_SERIES_SEASONS 

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
            query.edit_message_text("Error processing your selection. Please try again.")
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
                query.edit_message_text("Error retrieving series details. Please try again later.")
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