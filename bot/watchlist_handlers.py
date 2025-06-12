from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, ParseMode
from telegram.ext import CallbackContext
import logging

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class WatchlistHandlers:
    def __init__(self, db, tmdb):
        self.db = db
        self.tmdb = tmdb

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
                    "Сначала вам нужно добавить сериал. Используйте команду /add или кнопку ниже.",
                    reply_markup=reply_markup
                )
            else:
                update.message.reply_text(
                    "Сначала вам нужно добавить сериал. Используйте команду /add или кнопку ниже.",
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
                        InlineKeyboardButton(f"✅ Просмотрено", callback_data=f"mark_watched_{series.id}"),
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
