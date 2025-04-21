# TV Series Tracker Bot

A Telegram bot that helps you keep track of TV series you're watching.

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