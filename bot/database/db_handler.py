from datetime import datetime
from .models import User, Series, UserSeries, get_session, init_db

class DBHandler:
    def __init__(self):
        self.session = get_session()
        
    def add_user(self, telegram_id, username=None, first_name=None, last_name=None):
        """Add a new user to the database or update existing one"""
        user = self.session.query(User).filter(User.telegram_id == str(telegram_id)).first()
        
        if user is None:
            user = User(
                telegram_id=str(telegram_id),
                username=username,
                first_name=first_name,
                last_name=last_name
            )
            self.session.add(user)
            self.session.commit()
        else:
            # Update user info
            user.username = username
            user.first_name = first_name
            user.last_name = last_name
            self.session.commit()
            
        return user
    
    def get_user(self, telegram_id):
        """Get a user by their Telegram ID"""
        return self.session.query(User).filter(User.telegram_id == str(telegram_id)).first()
    
    def add_series(self, tmdb_id, name, year=None, total_seasons=None):
        """Add a new series or update an existing one"""
        series = self.session.query(Series).filter(Series.tmdb_id == tmdb_id).first()
        
        if series is None:
            series = Series(
                tmdb_id=tmdb_id,
                name=name,
                year=year,
                total_seasons=total_seasons
            )
            self.session.add(series)
        else:
            # Update series info
            series.name = name
            series.year = year
            series.total_seasons = total_seasons
            series.last_update = datetime.utcnow()
            
        self.session.commit()
        return series
    
    def get_series(self, tmdb_id):
        """Get a series by its TMDB ID"""
        return self.session.query(Series).filter(Series.tmdb_id == tmdb_id).first()
    
    def add_user_series(self, user_id, series_id, current_season=1, current_episode=0, in_watchlist=False):
        """Add a series to a user's watch list or watchlist"""
        user_series = self.session.query(UserSeries).filter(
            UserSeries.user_id == user_id,
            UserSeries.series_id == series_id
        ).first()
        
        if user_series is None:
            user_series = UserSeries(
                user_id=user_id,
                series_id=series_id,
                current_season=current_season,
                current_episode=current_episode,
                is_watching=not in_watchlist,
                in_watchlist=in_watchlist
            )
            self.session.add(user_series)
        else:
            # Update existing entry
            user_series.current_season = current_season
            user_series.current_episode = current_episode
            user_series.is_watching = not in_watchlist
            user_series.in_watchlist = in_watchlist
            user_series.last_updated = datetime.utcnow()
            
        self.session.commit()
        return user_series
    
    def update_user_series(self, user_id, series_id, current_season, current_episode):
        """Update user's progress on a series"""
        user_series = self.session.query(UserSeries).filter(
            UserSeries.user_id == user_id,
            UserSeries.series_id == series_id
        ).first()
        
        if user_series:
            user_series.current_season = current_season
            user_series.current_episode = current_episode
            user_series.last_updated = datetime.utcnow()
            self.session.commit()
            return user_series
        
        return None
    
    def remove_user_series(self, user_id, series_id):
        """Remove a series from a user's watch list"""
        user_series = self.session.query(UserSeries).filter(
            UserSeries.user_id == user_id,
            UserSeries.series_id == series_id
        ).first()
        
        if user_series:
            self.session.delete(user_series)
            self.session.commit()
            return True
        
        return False
    
    def get_user_series_list(self, user_id, watchlist_only=False, watched_only=False):
        """Get all series a user is watching, has in watchlist, or has watched"""
        query = self.session.query(UserSeries, Series).join(
            Series, UserSeries.series_id == Series.id
        ).filter(UserSeries.user_id == user_id)
        
        if watchlist_only:
            query = query.filter(UserSeries.in_watchlist == True)
        elif watched_only:
            query = query.filter(UserSeries.is_watched == True)
        else:
            query = query.filter(UserSeries.is_watching == True)
            
        return query.all()
    
    def get_all_watching_users(self, series_id):
        """Get all users watching a specific series"""
        return self.session.query(UserSeries, User).join(
            User, UserSeries.user_id == User.id
        ).filter(UserSeries.series_id == series_id).all()
        
    def move_to_watching(self, user_id, series_id):
        """Move a series from watchlist to watching"""
        user_series = self.session.query(UserSeries).filter(
            UserSeries.user_id == user_id,
            UserSeries.series_id == series_id
        ).first()
        
        if user_series:
            user_series.is_watching = True
            user_series.in_watchlist = False
            user_series.last_updated = datetime.utcnow()
            self.session.commit()
            return True
        
        return False
        
    def move_to_watchlist(self, user_id, series_id):
        """Move a series from watching to watchlist"""
        user_series = self.session.query(UserSeries).filter(
            UserSeries.user_id == user_id,
            UserSeries.series_id == series_id
        ).first()
        
        if user_series:
            user_series.is_watching = False
            user_series.in_watchlist = True
            user_series.last_updated = datetime.utcnow()
            self.session.commit()
            return True
        
        return False
        
    def mark_as_watched(self, user_id, series_id):
        """Mark a series as watched"""
        user_series = self.session.query(UserSeries).filter(
            UserSeries.user_id == user_id,
            UserSeries.series_id == series_id
        ).first()
        
        if user_series:
            user_series.is_watched = True
            user_series.watched_date = datetime.utcnow()
            user_series.is_watching = False
            user_series.in_watchlist = False
            user_series.last_updated = datetime.utcnow()
            self.session.commit()
            return True
        
        return False
        
    def add_watched_series(self, user_id, series_id):
        """Add a series as already watched"""
        user_series = self.session.query(UserSeries).filter(
            UserSeries.user_id == user_id,
            UserSeries.series_id == series_id
        ).first()
        
        if user_series is None:
            user_series = UserSeries(
                user_id=user_id,
                series_id=series_id,
                is_watched=True,
                is_watching=False,
                in_watchlist=False,
                watched_date=datetime.utcnow()
            )
            self.session.add(user_series)
        else:
            user_series.is_watched = True
            user_series.is_watching = False
            user_series.in_watchlist = False
            user_series.watched_date = datetime.utcnow()
            user_series.last_updated = datetime.utcnow()
            
        self.session.commit()
        return user_series
        
    def close(self):
        """Close the database session"""
        self.session.close() 