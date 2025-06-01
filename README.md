# TV Series Tracker Bot

A Telegram bot for tracking TV series, managing watchlists, and receiving notifications about new episodes.

## Features

- Add TV series to your watch list
- Update seasons/episodes you've watched
- Get notifications for new episode/season releases
- List all series you're currently watching
- Remove series from your list

## Setup

1. Clone this repository
2. Create a virtual environment: `python -m venv venv`
3. Activate the virtual environment:
   - Windows: `venv\Scripts\activate`
   - macOS/Linux: `source venv/bin/activate`
4. Install dependencies: `pip install -r requirements.txt`
5. Edit the `.env` file and add your TMDB API key
6. Run the bot: `./venv/bin/python run.py`

## Commands

- `/start` - Start the bot
- `/help` - Show available commands
- `/add` - Add a new TV series
- `/list` - List all TV series you're watching
- `/update` - Update your progress on a series
- `/remove` - Remove a series from your list

## Notes

You need to obtain a TMDB API key from [https://www.themoviedb.org/](https://www.themoviedb.org/) and set it in the `.env` file.
Also, make sure your Telegram bot token is correct in the `.env` file. 

# View logs
docker logs -f serials-bot

# Restart the bot
docker restart serials-bot

# Update the bot
git pull
docker build -t serials-bot .
docker stop serials-bot
docker rm serials-bot
docker run -d --name serials-bot --restart unless-stopped -p 8443:8443 --env-file .env serials-bot 

## Database Setup

### PostgreSQL Setup

1. Install PostgreSQL if you haven't already:
```bash
# For macOS
brew install postgresql

# For Ubuntu/Debian
sudo apt-get install postgresql postgresql-contrib
```

2. Create a new database:
```bash
# Connect to PostgreSQL
psql postgres

# Create database
CREATE DATABASE serials_bot;

# Create user (optional)
CREATE USER your_username WITH PASSWORD 'your_password';

# Grant privileges
GRANT ALL PRIVILEGES ON DATABASE serials_bot TO your_username;

# Exit psql
\q
```

3. Set up environment variables in `.env`:
```
# PostgreSQL Configuration
POSTGRES_USER=your_username
POSTGRES_PASSWORD=your_password
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=serials_bot
```

4. Initialize the database tables:
```bash
# Run the test connection script to create tables
python test_db_connection.py
```

### Database Schema

The bot uses the following tables:

1. `users` - Stores user information:
   - `id` (Primary Key)
   - `telegram_id` (Unique)
   - `username`
   - `first_name`
   - `last_name`
   - `joined_date`

2. `series` - Stores TV series information:
   - `id` (Primary Key)
   - `tmdb_id` (Unique)
   - `name`
   - `year`
   - `total_seasons`
   - `last_update`

3. `user_series` - Links users with their series:
   - `id` (Primary Key)
   - `user_id` (Foreign Key)
   - `series_id` (Foreign Key)
   - `current_season`
   - `current_episode`
   - `is_watching`
   - `in_watchlist`
   - `is_watched`
   - `watched_date`
   - `last_updated`

## Migration from SQLite to PostgreSQL

If you're migrating from SQLite to PostgreSQL:

1. Make sure your PostgreSQL database is set up and configured in `.env`

2. Run the migration script:
```bash
python migrate_db.py
```

The script will:
- Read data from your SQLite database
- Create tables in PostgreSQL
- Migrate all users, series, and user series relationships
- Handle any errors during migration

## Deployment

### Local Development

1. Set environment variables:
```
ENVIRONMENT=development
TELEGRAM_BOT_TOKEN=your_bot_token
TMDB_API_KEY=your_tmdb_api_key
```

2. Run the bot:
```bash
python -m bot.main
```

### Production Deployment (Render)

1. Set environment variables in Render:
```
ENVIRONMENT=production
TELEGRAM_BOT_TOKEN=your_bot_token
TMDB_API_KEY=your_tmdb_api_key
WEBHOOK_URL=https://your-render-service-url.onrender.com
POSTGRES_USER=your_render_db_user
POSTGRES_PASSWORD=your_render_db_password
POSTGRES_HOST=your_render_db_host
POSTGRES_PORT=5432
POSTGRES_DB=your_render_db_name
```

2. Deploy to Render:
- Connect your repository
- Set build command: `pip install -r requirements.txt`
- Set start command: `python -m bot.main`

## Bot Commands

- `/start` - Start the bot
- `/help` - Show help message
- `/add` - Add a new TV series to your watchlist
- `/list` - List all TV series you are watching
- `/update` - Update your progress on a series
- `/remove` - Remove a series from your watchlist
- `/watchlist` - View your future watchlist
- `/addwatch` - Add a series to your future watchlist
- `/watched` - List all watched series
- `/addwatched` - Add a new watched series 