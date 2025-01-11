import csv
from plexapi.server import PlexServer
from datetime import datetime
import os
import logging


# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


def fetch_watched_movies(plex, plex_library):
    library = plex.library.section(plex_library)
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


def main(plex_url, plex_token, plex_library, csv_limit, csv_file):
    plex = PlexServer(plex_url, plex_token)

    watched_movies = fetch_watched_movies(plex, plex_library)
    watched_movies_sorted = sorted(
        watched_movies,
        key=lambda x: (
            datetime.strptime(x["WatchedDate"], "%Y-%m-%d")
            if x["WatchedDate"] != "Never"
            else datetime.min
        ),
        reverse=True,
    )
    export_to_csv(watched_movies_sorted[:csv_limit], csv_file)

    if not os.path.exists(csv_file):
        logging.error(f"Failed to export data to {csv_file}")
        return False

    return True
