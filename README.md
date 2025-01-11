# Description
The tool exports Plex history to CSV file and imports the file to your Letterboxd profile.

Letterboxd doesn't have public API, so the tool uses [Playwright](https://playwright.dev) to interact with the website.

# Usage
1. Create `.env` file:
LETTERBOXD_USERNAME=...
LETTERBOXD_PASSWORD=...
PLEX_TOKEN=...
PLEX_URL=...

1. Start the container:
> docker-compose up -d

# Environmental variables
| Variable            | Description                                         | Default                |
| ------------------- | --------------------------------------------------- | ---------------------- |
| LETTERBOXD_USERNAME | Letterboxd username or email                        | -                      |
| LETTERBOXD_PASSWORD | Letterboxd password                                 | -                      |
| PLEX_URL            | Plex URL                                            | http://localhost:32400 |
| PLEX_TOKEN          | [How to find Plex token](https://shorturl.at/BXVyi) | -                      |
| PLEX_LIBRARY        | Name of Plex library for export                     | Films                  |
| TELEGRAM_BOT_TOKEN  | Optional. Telegram bot token to get notifications   | -                      |
| TELEGRAM_CHAT_ID    | Optional. Telegram chat ID to get notifications     | -                      |
| CSV_LIMIT           | Number of items to include into CSV file            | 10                     |
