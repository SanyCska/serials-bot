from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, ParseMode
from telegram.ext import CallbackContext, ConversationHandler, MessageHandler, Filters, CommandHandler, CallbackQueryHandler
import logging

# Conversation states
SELECTING_SERIES, SELECTING_SEASON, SELECTING_EPISODE, MANUAL_EPISODE_ENTRY, MANUAL_SERIES_NAME, MANUAL_SERIES_YEAR, MANUAL_SERIES_SEASONS, SEARCH_WATCHED, SERIES_SELECTION, SELECT_SEASON, SELECT_EPISODE, MARK_WATCHED, MANUAL_SEASON_ENTRY = range(13)

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class WatchLaterHandlers:
    def __init__(self, db, tmdb):
        self.db = db
        self.tmdb = tmdb

    def add_to_watch_later_start(self, update: Update, context: CallbackContext) -> int:
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

    def view_watch_later_start(self, update: Update, context: CallbackContext) -> int:
        """Start the watchlist viewing process."""
        # Get user from database
        user = self.db.get_user(
            update.effective_user.id if update.effective_user else update.callback_query.from_user.id)

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
                    InlineKeyboardButton(f"❌ Удалить", callback_data=f"watchlist_series_{series.id}")
                ],
                [
                    InlineKeyboardButton(f"▶️ Начать просмотр", callback_data=f"move_watching_{series.id}"),
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

    def handle_watch_later_actions(self, update: Update, context: CallbackContext) -> int:
        """Handle watch later actions - move to watching or remove"""
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
