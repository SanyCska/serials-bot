import schedule
import time
import threading
import logging
from datetime import datetime, timedelta
from bot.database.db_handler import DBHandler
from bot.tmdb_api import TMDBApi

logger = logging.getLogger(__name__)

class NotificationScheduler:
    def __init__(self, bot):
        self.bot = bot
        self.db = DBHandler()
        self.tmdb = TMDBApi()
        self.running = False
        self.thread = None
        
    def start(self):
        """Start the scheduler in a separate thread"""
        if self.running:
            return
            
        self.running = True
        
        # Schedule the check to run daily at a specific time (e.g., 10 AM)
        schedule.every().day.at("10:00").do(self.check_for_updates)
        
        # Also schedule a full check for new content once a week
        schedule.every().monday.at("12:00").do(self.full_content_check)
        
        # Start the scheduling thread
        self.thread = threading.Thread(target=self._run_continuously)
        self.thread.daemon = True
        self.thread.start()
        
        logger.info("Notification scheduler started")
        
    def stop(self):
        """Stop the scheduler thread"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=1)
        logger.info("Notification scheduler stopped")
        
    def _run_continuously(self):
        """Run the scheduler continuously"""
        while self.running:
            schedule.run_pending()
            time.sleep(60)  # Sleep for 1 minute between checks
            
    def check_for_updates(self):
        """Check for updates for all series in the database"""
        logger.info("Checking for TV series updates...")
        
        try:
            # Get all series in the database
            session = self.db.session
            series_list = session.query(self.db.Series).all()
            
            for series in series_list:
                # Get the list of users watching this series
                watching_users = self.db.get_all_watching_users(series.id)
                
                if not watching_users:
                    continue
                    
                # Check for new episodes/seasons for this series
                # Use the last update time from the series table
                last_check = series.last_update
                if not last_check:
                    last_check = datetime.utcnow() - timedelta(days=7)
                
                new_content = self.tmdb.check_new_episodes(series.tmdb_id, last_check)
                
                # Update the last_update time for this series
                series.last_update = datetime.utcnow()
                session.commit()
                
                # If there's new content, notify the users
                if new_content:
                    for user_series, user in watching_users:
                        self._send_notifications(user, series, new_content)
                        
        except Exception as e:
            logger.error(f"Error checking for updates: {e}")
            
    def full_content_check(self):
        """Run a full check for all content, including checking existing series for metadata updates"""
        logger.info("Running full content check...")
        
        try:
            # Get all series in the database
            session = self.db.session
            series_list = session.query(self.db.Series).all()
            
            for series in series_list:
                # Update series metadata
                series_details = self.tmdb.get_series_details(series.tmdb_id)
                
                if series_details:
                    series.name = series_details['name']
                    series.year = series_details['year']
                    series.total_seasons = series_details['total_seasons']
                    series.last_update = datetime.utcnow()
                    session.commit()
                    
            # Now run the regular update check
            self.check_for_updates()
                    
        except Exception as e:
            logger.error(f"Error in full content check: {e}")
            
    def _send_notifications(self, user, series, new_content):
        """Send notifications to a user about new content"""
        try:
            telegram_id = user.telegram_id
            
            for content in new_content:
                if content['type'] == 'season':
                    message = f"🎬 New season alert! 🎬\n\n*{series.name}* Season {content['number']} is now available!"
                    if 'air_date' in content and content['air_date']:
                        message += f"\nReleased on {content['air_date']}"
                        
                    self.bot.send_message(chat_id=telegram_id, text=message, parse_mode='Markdown')
                    
                elif content['type'] == 'episode':
                    message = f"📺 New episode alert! 📺\n\n*{series.name}* S{content['season']}E{content['number']} \"{content['name']}\" is now available!"
                    if 'air_date' in content and content['air_date']:
                        message += f"\nReleased on {content['air_date']}"
                        
                    self.bot.send_message(chat_id=telegram_id, text=message, parse_mode='Markdown')
                    
        except Exception as e:
            logger.error(f"Error sending notification: {e}") 