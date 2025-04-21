from tmdbv3api import TMDb, TV
import os
from dotenv import load_dotenv
import datetime
import logging

load_dotenv()

logger = logging.getLogger(__name__)

class TMDBApi:
    def __init__(self):
        self.tmdb = TMDb()
        self.tmdb.api_key = os.getenv('TMDB_API_KEY')
        self.tv = TV()
        
    def search_series(self, query):
        """Search for TV series by name"""
        try:
            results = self.tv.search(query)
            return [
                {
                    'id': show.id,
                    'name': show.name,
                    'year': self._extract_year(show.first_air_date),
                    'overview': show.overview if hasattr(show, 'overview') else None,
                }
                for show in results[:5]  # Limit to 5 results
            ]
        except Exception as e:
            logger.error(f"Error searching for series: {e}")
            return []

    def get_series_details(self, series_id):
        """Get details for a specific TV series"""
        try:
            show = self.tv.details(series_id)
            
            return {
                'id': show.id,
                'name': show.name,
                'year': self._extract_year(show.first_air_date),
                'total_seasons': len(show.seasons),
                'seasons': [
                    {
                        'season_number': season.season_number,
                        'episode_count': season.episode_count,
                        'name': season.name,
                        'air_date': season.air_date
                    }
                    for season in show.seasons if season.season_number > 0  # Skip specials (season 0)
                ],
                'status': show.status,
                'overview': show.overview if hasattr(show, 'overview') else None,
            }
        except Exception as e:
            logger.error(f"Error getting series details: {e}")
            return None
            
    def get_season_details(self, series_id, season_number):
        """Get details for a specific season"""
        try:
            season = self.tv.season(series_id, season_number)
            
            # Check if we got valid data
            if not hasattr(season, 'episodes'):
                return None
                
            return {
                'season_number': season_number,
                'episode_count': len(season.episodes),
                'episodes': [
                    {
                        'episode_number': episode.episode_number,
                        'name': episode.name,
                        'air_date': episode.air_date,
                    }
                    for episode in season.episodes
                ],
            }
        except Exception as e:
            logger.error(f"Error getting season details: {e}")
            return None
    
    def check_new_episodes(self, series_id, last_check_date=None):
        """Check if there are new episodes or seasons since the last check"""
        try:
            # Convert last_check_date from string to datetime if needed
            if isinstance(last_check_date, str):
                last_check_date = datetime.datetime.fromisoformat(last_check_date)
            
            # If no last check date provided, set it to 7 days ago
            if last_check_date is None:
                last_check_date = datetime.datetime.now() - datetime.timedelta(days=7)
                
            show = self.tv.details(series_id)
            
            new_content = []
            
            # Check for new seasons
            for season in show.seasons:
                if season.season_number == 0:  # Skip specials (season 0)
                    continue
                    
                if season.air_date and self._parse_date(season.air_date) > last_check_date:
                    new_content.append({
                        'type': 'season',
                        'number': season.season_number,
                        'name': season.name,
                        'air_date': season.air_date
                    })
                else:
                    # Check for new episodes in recent seasons
                    season_details = self.get_season_details(series_id, season.season_number)
                    if season_details:
                        for episode in season_details['episodes']:
                            if episode['air_date'] and self._parse_date(episode['air_date']) > last_check_date:
                                new_content.append({
                                    'type': 'episode',
                                    'season': season.season_number,
                                    'number': episode['episode_number'],
                                    'name': episode['name'],
                                    'air_date': episode['air_date']
                                })
            
            return new_content
                
        except Exception as e:
            logger.error(f"Error checking for new episodes: {e}")
            return []
    
    def _extract_year(self, date_str):
        """Extract the year from a date string"""
        if not date_str:
            return None
            
        try:
            return int(date_str.split('-')[0])
        except (IndexError, ValueError):
            return None
            
    def _parse_date(self, date_str):
        """Parse a date string into a datetime object"""
        if not date_str:
            return None
            
        try:
            return datetime.datetime.strptime(date_str, '%Y-%m-%d')
        except ValueError:
            return None 