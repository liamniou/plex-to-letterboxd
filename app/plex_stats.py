import csv
from plexapi.server import PlexServer
from datetime import datetime
import os
import logging


# Configuration
PLEX_URL = os.getenv("PLEX_URL")
PLEX_TOKEN = os.getenv("PLEX_TOKEN")
CSV_LIMIT = int(os.getenv("CSV_LIMIT", 10))
CSV_FILE = os.getenv("CSV_FILE", "file.csv")


# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


def fetch_watched_movies(plex):
    library = plex.library.section("Films")
    movies = library.all()
    watched_movies = []

    for movie in movies:
        if movie.isWatched:
            logging.info(f"Processing {movie.title} ({movie.lastViewedAt})")
            guids = movie.guids
            for guid in guids:
                if guid.id.startswith("imdb"):
                    imdb_id = guid.id.split("://")[1]
                if guid.id.startswith("tmdb"):
                    tmdb_id = guid.id.split("://")[1]
            watched_movies.append(
                {
                    "imdbID": imdb_id,
                    "tmdbID": tmdb_id,
                    "Title": movie.title,
                    "Year": movie.year,
                    "Rating10": (
                        movie.userRating if movie.userRating is not None else "N/A"
                    ),
                    "WatchedDate": (
                        movie.lastViewedAt.strftime("%Y-%m-%d")
                        if movie.lastViewedAt
                        else "Never"
                    ),
                    "Rewatch": "true" if movie.viewCount > 1 else "false",
                }
            )
    return watched_movies


def export_to_csv(movies, file_path):
    try:
        with open(file_path, mode="w", newline="") as file:
            writer = csv.DictWriter(
                file, fieldnames=["imdbID", "tmdbID", "Title", "Year", "Rating10", "WatchedDate", "Rewatch"]
            )
            writer.writeheader()
            writer.writerows(movies)
        logging.info(f"Data successfully exported to {file_path}")
    except Exception as e:
        logging.error(f"Error writing to CSV file: {e}")


def main():
    plex = PlexServer(PLEX_URL, PLEX_TOKEN)

    watched_movies = fetch_watched_movies(plex)
    watched_movies_sorted = sorted(
        watched_movies,
        key=lambda x: (
            datetime.strptime(x["WatchedDate"], "%Y-%m-%d")
            if x["WatchedDate"] != "Never"
            else datetime.min
        ),
        reverse=True,
    )
    export_to_csv(watched_movies_sorted[:CSV_LIMIT], CSV_FILE)

    if not os.path.exists(CSV_FILE):
        logging.error(f"Failed to export data to {CSV_FILE}")
        return False

    return True
