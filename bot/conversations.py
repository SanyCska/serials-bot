from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, ParseMode
from telegram.ext import CallbackContext, ConversationHandler, MessageHandler, Filters
import logging
import random

from bot.database.db_handler import DBHandler
from bot.tmdb_api import TMDBApi

# Conversation states
SELECTING_SERIES, SELECTING_SEASON, SELECTING_EPISODE, MANUAL_EPISODE_ENTRY, MANUAL_SERIES_NAME, MANUAL_SERIES_YEAR, MANUAL_SERIES_SEASONS, SEARCH_WATCHED, SERIES_SELECTION, SELECT_SEASON, SELECT_EPISODE, MARK_WATCHED = range(12)

# Callback data patterns
SERIES_PATTERN = "series_{}"
WATCHLIST_SERIES_PATTERN = "watchlist_series_{}"
SEASON_PATTERN = "season_{}_{}"  # series_id, season_number
EPISODE_PATTERN = "episode_{}_{}_{}"  # series_id, season_number, episode_number
MANUAL_ENTRY_PATTERN = "manual_{}_{}"  # series_id, season_number
MANUAL_ADD_PATTERN = "manual_add"
MOVE_TO_WATCHING = "move_watching_{}"  # series_id
MOVE_TO_WATCHLIST = "move_watchlist_{}"  # series_id
CANCEL_PATTERN = "cancel"

logger = logging.getLogger(__name__)

class ConversationManager:
    """Manages conversation states for the bot."""
    def __init__(self):
        self.db = DBHandler()
        self.tmdb = TMDBApi()
        
    def add_series_start(self, update: Update, context: CallbackContext) -> int:
        """Start the add series conversation"""
        # Handle callback query case
        if update.callback_query:
            update.callback_query.edit_message_text(
                "Please send me the name of the TV series you want to add."
            )
        else:
            update.message.reply_text(
                "Please send me the name of the TV series you want to add."
            )
        
        return SELECTING_SERIES
        
    def search_series(self, update: Update, context: CallbackContext, query=None, is_watched=False) -> int:
        """Search for TV series based on user input"""
        if query is None:
            query = update.message.text.strip()
        
        # Save the query in user_data
        context.user_data["series_query"] = query
        context.user_data["is_watched"] = is_watched
        
        # Search for TV series with the TMDB API
        results = self.tmdb.search_series(query)
        
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
        keyboard.append([InlineKeyboardButton("Add manually (not in list)", callback_data=MANUAL_ADD_PATTERN)])
            
        # Add a cancel button
        keyboard.append([InlineKeyboardButton("Cancel", callback_data=CANCEL_PATTERN)])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if not results:
            update.message.reply_text(
                "No TV series found with that name. Would you like to add it manually?",
                reply_markup=reply_markup
            )
        else:
            update.message.reply_text(
                "Here are the TV series I found. Please select one or add manually:",
                reply_markup=reply_markup
            )
        
        return SELECTING_SERIES
        
    def series_selected(self, update: Update, context: CallbackContext) -> int:
        """Handle series selection"""
        query = update.callback_query
        query.answer()
        
        if query.data == CANCEL_PATTERN:
            query.edit_message_text("Operation cancelled.")
            return ConversationHandler.END
            
        # Check if this is a manual add request
        if query.data == MANUAL_ADD_PATTERN:
            query.edit_message_text(
                "Please enter the exact name of the TV series you want to add:"
            )
            return MANUAL_SERIES_NAME
            
        # Extract series ID from callback data
        series_id = int(query.data.split("_")[1])
        
        # Get series details from TMDB
        series_details = self.tmdb.get_series_details(series_id)
        
        if not series_details:
            query.edit_message_text("Error retrieving series details. Please try again later.")
            return ConversationHandler.END
            
        # Save the series details in user_data
        context.user_data["selected_series"] = series_details
        
        # Add the user to the database
        user = self.db.add_user(
            query.from_user.id,
            query.from_user.username,
            query.from_user.first_name,
            query.from_user.last_name
        )
        
        # Add series to database
        series = self.db.add_series(
            series_details['id'],
            series_details['name'],
            series_details['year'],
            series_details['total_seasons']
        )
        
        # Check if this is for adding a watched series
        if context.user_data.get("is_watched", False):
            logger.info(f"Adding watched series: {series.name} for user {user.id}")
            if self.db.add_watched_series(user.id, series.id):
                query.edit_message_text(
                    f"I've added '{series_details['name']}' to your watched series list!"
                )
            else:
                query.edit_message_text(
                    "Error adding series to your watched list. Please try again later."
                )
            return ConversationHandler.END
        
        # Add to user's watchlist or watching list based on context
        is_watchlist = context.user_data.get("add_to_watchlist", False)
        self.db.add_user_series(user.id, series.id, in_watchlist=is_watchlist)
        
        # If this is a watchlist addition, we're done
        if is_watchlist:
            query.edit_message_text(
                f"I've added '{series_details['name']}' to your watchlist for future viewing!"
            )
            # Clean up
            if "add_to_watchlist" in context.user_data:
                del context.user_data["add_to_watchlist"]
                
            return ConversationHandler.END
            
        # Otherwise continue with season selection for watching now
        if series_details['seasons']:
            keyboard = []
            for season in series_details['seasons']:
                keyboard.append([
                    InlineKeyboardButton(
                        f"Season {season['season_number']}",
                        callback_data=SEASON_PATTERN.format(series_id, season['season_number'])
                    )
                ])
                
            # Add a cancel button
            keyboard.append([InlineKeyboardButton("Cancel", callback_data=CANCEL_PATTERN)])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            query.edit_message_text(
                f"I've added '{series_details['name']}' to your watchlist!\n\n"
                "Which season are you currently watching?",
                reply_markup=reply_markup
            )
            
            return SELECTING_SEASON
        else:
            query.edit_message_text(
                f"I've added '{series_details['name']}' to your watchlist!"
            )
            
            return ConversationHandler.END
            
    def manual_series_name_entered(self, update: Update, context: CallbackContext) -> int:
        """Handle manual series name entry"""
        series_name = update.message.text.strip()
        
        if not series_name:
            update.message.reply_text("Please enter a valid series name or use /cancel to cancel.")
            return MANUAL_SERIES_NAME
        
        # Save the series name
        context.user_data["manual_series_name"] = series_name
        
        update.message.reply_text(
            "Please enter the year the series started (e.g., 2020) or 0 if unknown:"
        )
        
        return MANUAL_SERIES_YEAR
        
    def manual_series_year_entered(self, update: Update, context: CallbackContext) -> int:
        """Handle manual series year entry"""
        try:
            year_text = update.message.text.strip()
            year = int(year_text)
            
            if year < 0:
                update.message.reply_text("Year cannot be negative. Please enter a valid year or 0 if unknown:")
                return MANUAL_SERIES_YEAR
                
            # Save the year (or None if 0)
            context.user_data["manual_series_year"] = year if year > 0 else None
            
            update.message.reply_text(
                "Please enter the total number of seasons (or best estimate):"
            )
            
            return MANUAL_SERIES_SEASONS
            
        except ValueError:
            update.message.reply_text("Please enter a valid number for the year or use /cancel to cancel.")
            return MANUAL_SERIES_YEAR
            
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
            
            # Add to user's watchlist
            self.db.add_user_series(user.id, series.id)
            
            # Create keyboard for season selection
            keyboard = []
            for season_num in range(1, total_seasons + 1):
                keyboard.append([
                    InlineKeyboardButton(
                        f"Season {season_num}",
                        callback_data=SEASON_PATTERN.format(manual_id, season_num)
                    )
                ])
                
            # Add a cancel button
            keyboard.append([InlineKeyboardButton("Cancel", callback_data=CANCEL_PATTERN)])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            update.message.reply_text(
                f"I've added '{context.user_data['manual_series_name']}' to your watchlist!\n\n"
                "Which season are you currently watching?",
                reply_markup=reply_markup
            )
            
            return SELECTING_SEASON
            
        except ValueError:
            update.message.reply_text("Please enter a valid number for the seasons or use /cancel to cancel.")
            return MANUAL_SERIES_SEASONS
        
    def season_selected(self, update: Update, context: CallbackContext) -> int:
        """Handle season selection"""
        query = update.callback_query
        query.answer()
        
        if query.data == CANCEL_PATTERN:
            query.edit_message_text("Season selection cancelled. The series has been added to your watchlist.")
            return ConversationHandler.END
            
        # Extract series_id and season_number from callback data
        _, series_id, season_number = query.data.split("_")
        series_id, season_number = int(series_id), int(season_number)
        
        # Save the season number in user_data
        context.user_data["selected_season"] = season_number
        context.user_data["selected_series_id"] = series_id
        
        # Get season details from TMDB
        season_details = self.tmdb.get_season_details(series_id, season_number)
        
        if not season_details or not season_details['episodes']:
            keyboard = [
                [InlineKeyboardButton("Enter episode number manually", callback_data=MANUAL_ENTRY_PATTERN.format(series_id, season_number))],
                [InlineKeyboardButton("Set as not started (Episode 0)", callback_data=EPISODE_PATTERN.format(series_id, season_number, 0))],
                [InlineKeyboardButton("Cancel", callback_data=CANCEL_PATTERN)]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            query.edit_message_text(
                f"I couldn't retrieve episodes for this season. Would you like to enter an episode number manually?",
                reply_markup=reply_markup
            )
            
            return SELECTING_EPISODE
            
        # Create keyboard with episodes
        keyboard = []
        
        # Group episodes into rows of 3
        row = []
        for episode in season_details['episodes']:
            row.append(
                InlineKeyboardButton(
                    f"Ep {episode['episode_number']}",
                    callback_data=EPISODE_PATTERN.format(series_id, season_number, episode['episode_number'])
                )
            )
            
            if len(row) == 3:
                keyboard.append(row)
                row = []
                
        # Add any remaining episodes
        if row:
            keyboard.append(row)
            
        # Add a manual entry option
        keyboard.append([InlineKeyboardButton("Enter manually", callback_data=MANUAL_ENTRY_PATTERN.format(series_id, season_number))])
            
        # Add a cancel button
        keyboard.append([InlineKeyboardButton("Cancel", callback_data=CANCEL_PATTERN)])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        query.edit_message_text(
            f"Which episode of Season {season_number} are you currently watching?",
            reply_markup=reply_markup
        )
        
        return SELECTING_EPISODE
        
    def episode_selected(self, update: Update, context: CallbackContext) -> int:
        """Handle episode selection"""
        query = update.callback_query
        query.answer()
        
        if query.data == CANCEL_PATTERN:
            query.edit_message_text("Episode selection cancelled. The series has been added to your watchlist.")
            return ConversationHandler.END
            
        # Check if this is a manual entry request
        if query.data.startswith("manual_"):
            # Format is manual_series_id_season_number
            data_parts = query.data.split("_")
            if len(data_parts) != 3:
                query.edit_message_text("Error processing your request. Please try again.")
                return ConversationHandler.END
                
            series_id = int(data_parts[1])
            season_number = int(data_parts[2])
            context.user_data["selected_series_id"] = series_id
            context.user_data["selected_season"] = season_number
            
            query.edit_message_text(
                f"Please enter the episode number for Season {season_number} you are currently watching:"
            )
            
            return MANUAL_EPISODE_ENTRY
            
        # Extract series_id, season_number, and episode_number from callback data
        _, series_id, season_number, episode_number = query.data.split("_")
        series_id = int(series_id)
        season_number = int(season_number)
        episode_number = int(episode_number)
        
        # Update user's progress
        user = self.db.get_user(query.from_user.id)
        series = self.db.get_series(series_id)
        
        if user and series:
            self.db.update_user_series(user.id, series.id, season_number, episode_number)
            
            query.edit_message_text(
                f"Great! I've updated your progress to Season {season_number}, Episode {episode_number}."
            )
        else:
            query.edit_message_text("Error updating your progress. Please try again later.")
            
        return ConversationHandler.END

    def manual_episode_entry(self, update: Update, context: CallbackContext) -> int:
        """Handle manual episode number entry"""
        try:
            episode_text = update.message.text.strip()
            
            try:
                episode_number = int(episode_text)
            except ValueError:
                update.message.reply_text(
                    "Please enter a valid episode number (only digits). Try again or use /cancel to cancel."
                )
                return MANUAL_EPISODE_ENTRY
            
            if episode_number < 0:
                update.message.reply_text(
                    "Episode number cannot be negative. Please enter a valid episode number or use /cancel to cancel."
                )
                return MANUAL_EPISODE_ENTRY
                
            series_id = context.user_data.get("selected_series_id")
            season_number = context.user_data.get("selected_season")
            
            # Log the values for debugging
            logger.info(f"Manual entry - series_id: {series_id}, season: {season_number}, episode: {episode_number}")
            
            if not series_id or not season_number:
                update.message.reply_text("Something went wrong. Please try again later.")
                return ConversationHandler.END
                
            # Update user's progress
            user = self.db.get_user(update.message.from_user.id)
            series = self.db.get_series(int(series_id))  # Ensure series_id is an integer
            
            if user and series:
                self.db.update_user_series(user.id, series.id, season_number, episode_number)
                
                update.message.reply_text(
                    f"Great! I've updated your progress to Season {season_number}, Episode {episode_number}."
                )
            else:
                update.message.reply_text("Error updating your progress. Please try again later.")
                
            return ConversationHandler.END
            
        except Exception as e:
            logger.error(f"Error in manual episode entry: {e}")
            update.message.reply_text(
                "An error occurred. Please try again or use /cancel to cancel."
            )
            return MANUAL_EPISODE_ENTRY
        
    def update_series_start(self, update: Update, context: CallbackContext) -> int:
        """Start the update series conversation"""
        # Get the user from database
        user_id = update.callback_query.from_user.id if update.callback_query else update.message.from_user.id
        user = self.db.get_user(user_id)
        
        if not user:
            message = "You need to add a series first. Use /add command."
            if update.callback_query:
                update.callback_query.answer()
                update.callback_query.edit_message_text(message)
            else:
                update.message.reply_text(message)
            return ConversationHandler.END
            
        user_series_list = self.db.get_user_series_list(user.id)
        
        if not user_series_list:
            message = "You're not watching any series yet. Use /add command to add one."
            if update.callback_query:
                update.callback_query.answer()
                update.callback_query.edit_message_text(message)
            else:
                update.message.reply_text(message)
            return ConversationHandler.END
            
        # Create inline keyboard with the user's series
        keyboard = []
        for user_series, series in user_series_list:
            keyboard.append([
                InlineKeyboardButton(
                    f"{series.name} (S{user_series.current_season}E{user_series.current_episode})",
                    callback_data=SERIES_PATTERN.format(series.tmdb_id)
                )
            ])
            
        # Add a cancel button
        keyboard.append([InlineKeyboardButton("Cancel", callback_data=CANCEL_PATTERN)])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message = "Which series do you want to update?"
        if update.callback_query:
            update.callback_query.answer()
            update.callback_query.edit_message_text(message, reply_markup=reply_markup)
        else:
            update.message.reply_text(message, reply_markup=reply_markup)
        
        return SELECTING_SERIES
        
    def remove_series_start(self, update: Update, context: CallbackContext) -> int:
        """Start the remove series conversation"""
        # Get the user from database
        user_id = update.callback_query.from_user.id if update.callback_query else update.message.from_user.id
        user = self.db.get_user(user_id)
        
        if not user:
            message = "You need to add a series first. Use /add command."
            if update.callback_query:
                update.callback_query.answer()
                update.callback_query.edit_message_text(message)
            else:
                update.message.reply_text(message)
            return ConversationHandler.END
            
        user_series_list = self.db.get_user_series_list(user.id)
        
        if not user_series_list:
            message = "You're not watching any series yet. Use /add command to add one."
            if update.callback_query:
                update.callback_query.answer()
                update.callback_query.edit_message_text(message)
            else:
                update.message.reply_text(message)
            return ConversationHandler.END
            
        # Create inline keyboard with the user's series
        keyboard = []
        for user_series, series in user_series_list:
            keyboard.append([
                InlineKeyboardButton(
                    f"{series.name}",
                    callback_data=SERIES_PATTERN.format(series.id)  # Use internal ID for removal
                )
            ])
            
        # Add a cancel button
        keyboard.append([InlineKeyboardButton("Cancel", callback_data=CANCEL_PATTERN)])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message = "Which series do you want to remove from your watchlist?"
        if update.callback_query:
            update.callback_query.answer()
            update.callback_query.edit_message_text(message, reply_markup=reply_markup)
        else:
            update.message.reply_text(message, reply_markup=reply_markup)
        
        context.user_data["action"] = "remove"  # Flag to indicate removal action
        
        return SELECTING_SERIES
        
    def cancel(self, update: Update, context: CallbackContext) -> int:
        """Cancel the conversation"""
        if update.message:
            update.message.reply_text("Operation cancelled.")
        elif update.callback_query:
            query = update.callback_query
            query.answer()
            query.edit_message_text("Operation cancelled.")
            
        # Clear user data
        context.user_data.clear()
        
        return ConversationHandler.END

    def add_to_watchlist_start(self, update: Update, context: CallbackContext) -> int:
        """Start the add to watchlist conversation"""
        # Handle callback query case
        if update.callback_query:
            update.callback_query.edit_message_text(
                "Please send me the name of the TV series you want to add to your watchlist."
            )
        else:
            update.message.reply_text(
                "Please send me the name of the TV series you want to add to your watchlist."
            )
        
        # Set flag to indicate watchlist operation
        context.user_data["add_to_watchlist"] = True
        
        return SELECTING_SERIES
    
    def view_watchlist_start(self, update: Update, context: CallbackContext) -> int:
        """Start the watchlist viewing process."""
        # Get user from database
        user = self.db.get_user(update.effective_user.id if update.effective_user else update.callback_query.from_user.id)
        
        if not user:
            message = "You need to add a series first. Use /add or /addwatch command."
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
                [InlineKeyboardButton("Add to Watchlist", callback_data="command_addwatch")],
                [InlineKeyboardButton("View Watching List", callback_data="command_list")],
                [InlineKeyboardButton("Help", callback_data="command_help")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            message = "Your watchlist is empty. Use /addwatch to add series you plan to watch."
            if update.callback_query:
                update.callback_query.answer()
                update.callback_query.edit_message_text(message, reply_markup=reply_markup)
            else:
                update.message.reply_text(message, reply_markup=reply_markup)
            return ConversationHandler.END
            
        # Send header message
        if update.callback_query:
            update.callback_query.answer()
            update.callback_query.edit_message_text("*Your Future Watchlist:*", parse_mode=ParseMode.MARKDOWN)
            chat_id = update.callback_query.message.chat_id
        else:
            update.message.reply_text("*Your Future Watchlist:*", parse_mode=ParseMode.MARKDOWN)
            chat_id = update.message.chat_id
            
        # Send each series as a separate message
        for user_series, series in user_series_list:
            year_str = f" ({series.year})" if series.year else ""
            message = f"• *{series.name}*{year_str}"
            
            # Create buttons specific to this series
            keyboard = [
                [
                    InlineKeyboardButton(f"▶️ Start Watching", callback_data=f"move_watching_{series.id}"),
                    InlineKeyboardButton(f"❌ Remove", callback_data=f"watchlist_series_{series.id}")
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
                InlineKeyboardButton("➕ Add to Watchlist", callback_data="command_addwatch"),
                InlineKeyboardButton("📺 View Watching", callback_data="command_list")
            ],
            [
                InlineKeyboardButton("🔄 Check Updates", callback_data="command_check"),
                InlineKeyboardButton("❓ Help", callback_data="command_help")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if update.callback_query:
            context.bot.send_message(
                chat_id=chat_id,
                text="*Actions:*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=reply_markup
            )
        else:
            update.message.reply_text(
                "*Actions:*",
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
                                        f"Season {season['season_number']}",
                                        callback_data=SEASON_PATTERN.format(series.tmdb_id, season['season_number'])
                                    )
                                ])
                    
                    # If no seasons from TMDB or manually added series, create buttons for seasons
                    if not keyboard and series.total_seasons:
                        for season_num in range(1, series.total_seasons + 1):
                            keyboard.append([
                                InlineKeyboardButton(
                                    f"Season {season_num}",
                                    callback_data=SEASON_PATTERN.format(series.id, season_num)
                                )
                            ])
                    
                    # Add cancel button
                    keyboard.append([InlineKeyboardButton("Cancel", callback_data=CANCEL_PATTERN)])
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    query.edit_message_text(
                        f"I've moved '{series_name}' to your watching list!\n\n"
                        "Which season are you currently watching?",
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
        
        # Check if there's text after the command
        query = update.message.text.replace('/addwatched', '').strip()
        if query:
            # If there's text after the command, go directly to search
            return self.search_series(update, context, query=query, is_watched=True)
        
        # If no text after command, ask for series name
        update.message.reply_text(
            'Please send me the name of the series you have watched:'
        )
        return SEARCH_WATCHED
        
    def search_watched_series(self, update: Update, context: CallbackContext) -> int:
        """Search for a series to mark as watched."""
        logger.info("Searching for watched series")
        return self.search_series(update, context, query=update.message.text, is_watched=True)
        
    def watched_series_selected(self, update: Update, context: CallbackContext) -> int:
        """Handle series selection for watched series."""
        query = update.callback_query
        query.answer()
        
        series_id = int(query.data.split('_')[1])
        user_id = update.effective_user.id
        
        series = self.tmdb.get_series_details(series_id)
        if not series:
            query.edit_message_text('Sorry, I could not find that series.')
            return ConversationHandler.END
            
        self.db.add_watched_series(user_id, series_id)
        
        query.edit_message_text(
            f'Added "{series.name}" to your watched series list!'
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
        
        keyboard.append([InlineKeyboardButton("Cancel", callback_data="cancel")])
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