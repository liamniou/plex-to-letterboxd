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
            # Respect Plex's finish threshold: a movie that is currently
            # resuming (viewOffset > 0) has not been played past Plex's
            # "video played threshold", so it is not actually finished.
            # This also skips unfinished rewatches of previously watched films.
            if getattr(movie, "viewOffset", None):
                logging.info(
                    f"Skipping {movie.title} - in progress (not finished per Plex threshold)"
                )
                continue

            # Only export movies the user has rated.
            if movie.userRating is None:
                logging.info(f"Skipping {movie.title} - no user rating")
                continue

            logging.info(f"Processing {movie.title} ({movie.lastViewedAt})")
            
            # Initialize IDs as empty
            imdb_id = ""
            tmdb_id = ""
            
            # Extract GUIDs safely
            try:
                guids = movie.guids
                for guid in guids:
                    if guid.id.startswith("imdb"):
                        imdb_id = guid.id.split("://")[1]
                    elif guid.id.startswith("tmdb"):
                        tmdb_id = guid.id.split("://")[1]
            except Exception as e:
                logging.warning(f"Could not extract GUIDs for {movie.title}: {e}")
            
            # Skip movies without any IDs (can't be matched by Letterboxd)
            if not imdb_id and not tmdb_id:
                logging.warning(f"Skipping {movie.title} - no IMDB or TMDB ID found")
                continue
            
            watched_movies.append(
                {
                    "imdbID": imdb_id,
                    "tmdbID": tmdb_id,
                    "Title": movie.title,
                    "Year": movie.year if movie.year else "",
                    "Rating10": (
                        movie.userRating if movie.userRating is not None else ""
                    ),
                    "WatchedDate": (
                        movie.lastViewedAt.strftime("%Y-%m-%d")
                        if movie.lastViewedAt
                        else ""
                    ),
                    "Rewatch": "true" if movie.viewCount and movie.viewCount > 1 else "false",
                }
            )
    
    logging.info(f"Found {len(watched_movies)} watched movies with valid IDs")
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


def main(plex_url, plex_token, plex_user, plex_library, csv_limit, csv_file):
    plex = PlexServer(plex_url, plex_token)

    if plex_user:
        logging.info(f"Switching to Plex user: {plex_user}")
        plex = plex.switchUser(plex_user)
    else:
        logging.info("Using the provided Plex token without switching users")

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

    # Print csv content for debugging
    try:
        with open(csv_file, mode="r") as file:
            content = file.read()
            logging.info(f"CSV Content:\n{content}")
    except Exception as e:
        logging.error(f"Error reading CSV file: {e}")

    if not os.path.exists(csv_file):
        logging.error(f"Failed to export data to {csv_file}")
        return False

    return True
