from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, ParseMode
from telegram.ext import CallbackContext, ConversationHandler, MessageHandler, Filters, CommandHandler, CallbackQueryHandler
import logging

# Conversation states
SELECTING_SERIES, SELECTING_SEASON, SELECTING_EPISODE, MANUAL_EPISODE_ENTRY, MANUAL_SERIES_NAME, MANUAL_SERIES_YEAR, MANUAL_SERIES_SEASONS, SEARCH_WATCHED, SERIES_SELECTION, SELECT_SEASON, SELECT_EPISODE, MARK_WATCHED, MANUAL_SEASON_ENTRY = range(13)


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
