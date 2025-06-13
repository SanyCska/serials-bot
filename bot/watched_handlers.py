from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, ParseMode
from telegram.ext import CallbackContext, MessageHandler, Filters, CommandHandler, ConversationHandler, CallbackQueryHandler
import logging
from bot.conversations import (
    ConversationManager,
    SELECTING_SERIES,
    CANCEL_PATTERN,
    SEARCH_WATCHED,
    SERIES_PATTERN
)
# Conversation states
SELECTING_SERIES, SELECTING_SEASON, SELECTING_EPISODE, MANUAL_EPISODE_ENTRY, MANUAL_SERIES_NAME, MANUAL_SERIES_YEAR, MANUAL_SERIES_SEASONS, SEARCH_WATCHED, SERIES_SELECTION, SELECT_SEASON, SELECT_EPISODE, MARK_WATCHED, MANUAL_SEASON_ENTRY = range(13)

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class WatchedHandlers:
    def __init__(self, db, tmdb):
        self.db = db
        self.tmdb = tmdb
        self.conversation_manager = ConversationManager(db, tmdb)

    def list_watched(self, update: Update, context: CallbackContext):
        """List all watched series for a user."""
        if update.callback_query:
            query = update.callback_query
            user = self.db.get_user(query.from_user.id)
            send = lambda text, **kwargs: query.edit_message_text(text, **kwargs)
        else:
            user = self.db.get_user(update.effective_user.id)
            send = lambda text, **kwargs: update.message.reply_text(text, **kwargs)

        if not user:
            send(
                "Вы ещё не добавили ни одного сериала. Используйте /addwatched, чтобы добавить первый просмотренный сериал.")
            return

        series_list = self.db.get_user_series_list(user.id, watched_only=True)

        if not series_list:
            keyboard = [
                [InlineKeyboardButton("Добавить просмотренный сериал", callback_data="command_addwatched")],
                [InlineKeyboardButton("Смотрю сейчас", callback_data="command_list")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            send(
                "Вы ещё не отметили ни один сериал как просмотренный.\nИспользуйте /addwatched, чтобы добавить уже просмотренные сериалы.",
                reply_markup=reply_markup
            )
            return

        message = "*Ваши просмотренные сериалы:*\n\n"
        for user_series, series in series_list:
            year_str = f" ({series.year})" if series.year else ""
            watched_date = user_series.watched_date.strftime(
                "%Y-%m-%d") if user_series.watched_date else "Неизвестная дата"
            message += f"• *{series.name}*{year_str}\n"
            message += f"  Просмотр завершён: {watched_date}\n\n"

        keyboard = [
            [InlineKeyboardButton("Добавить просмотренный сериал", callback_data="command_addwatched")],
            [InlineKeyboardButton("Смотрю сейчас", callback_data="command_list")],
            [InlineKeyboardButton("Помощь", callback_data="command_help")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        send(
            message,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )

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
            return self.conversation_manager.search_series(update, context, query=query, is_watched=True)

        # If no text after command, ask for series name
        update.message.reply_text(
            'Пожалуйста, отправьте мне название сериала, который вы уже посмотрели:'
        )
        return SEARCH_WATCHED

    def search_watched_series(self, update: Update, context: CallbackContext) -> int:
        """Search for a series to mark as watched."""
        logger.info("Searching for watched series")
        return self.conversation_manager.search_series(update, context, query=update.message.text, is_watched=True)

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

    def get_add_watched_conversation_handler(self, conversation_manager):
        return ConversationHandler(
            entry_points=[
                CommandHandler("addwatched", self.add_watched_series_start),
                CallbackQueryHandler(self.add_watched_series_start, pattern="^command_addwatched$")
            ],
            states={
                SEARCH_WATCHED: [
                    MessageHandler(Filters.text & ~Filters.command, self.search_watched_series),
                    CommandHandler("cancel", conversation_manager.cancel)
                ],
                SELECTING_SERIES: [
                    CallbackQueryHandler(self.watched_series_selected, pattern=f"^{SERIES_PATTERN.format('.*')}$"),
                    CallbackQueryHandler(conversation_manager.cancel, pattern=f"^{CANCEL_PATTERN}$")
                ]
            },
            fallbacks=[CommandHandler("cancel", conversation_manager.cancel)]
        )
