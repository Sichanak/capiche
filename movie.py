import functools
import logging
from datetime import datetime, timedelta
from imdb import Cinemagoer
import db

# Global logger & vars
LOG = logging.getLogger(__name__)
ia = Cinemagoer()  # Initialize Cinemagoer

def _catch_and_log(func):
    """
    Decorator function for catching and logging exceptions.
    """
    @functools.wraps(func)
    def try_func(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as err:
            LOG.error('Exception in %s: "%s"', func.__qualname__, err)
            return 'Unexpected error occurred.'
    return try_func

@_catch_and_log
def search(name):
    """
    Search for titles matching the name string and return a list of dictionaries.
    """
    imdb_results = ia.search_movie(name)  # Search for movies by name
    titles = []

    for result in imdb_results[:10]:  # Limit results to the first 10
        title_dict = get_fields(result)
        titles.append(title_dict)

    return titles

@_catch_and_log
def get_fields(imdb_data):
    """
    Extract fields for IMDb data (title, plot, year, genres, rating, etc.)
    """
    na_cover = 'https://i.imgur.com/A8SBkqe_d.jpg?maxwidth=640&shape=thumb&fidelity=medium'
    title_id = imdb_data.movieID  # Get IMDb ID

    fields = {
        'title': imdb_data.get('title', 'N/A'),
        'year': imdb_data.get('year', 'N/A'),
        'genres': ', '.join(imdb_data.get('genres', ['N/A'])),
        'rating': imdb_data.get('rating', 'N/A'),
        'plot': imdb_data.get('plot', ['N/A'])[0] if imdb_data.get('plot') else 'N/A',  # Safely get plot
        'kind': imdb_data.get('kind', 'N/A'),
        'cast': ', '.join([person['name'] for person in imdb_data.get('cast', [])[:4]]),
        'long imdb title': imdb_data.get('long imdb canonical title', 'N/A'),
        'cover url': imdb_data.get('cover url', na_cover),
        'full-size cover url': imdb_data.get('full-size cover url', na_cover),
        'id': title_id
    }

    # Optionally check for series-specific fields
    if 'series' in fields['kind'].lower():
        fields['series title'] = fields['title']  # Use existing title field
        fields['season'] = imdb_data.get('season', 'N/A')
        fields['episode'] = imdb_data.get('episode', 'N/A')

    return fields

@_catch_and_log
def reply_message(title):
    """
    Telegram reply message for selected inline result.
    """
    # movie or episode
    bold_fields = ['series title', 'title', 'plot', 'season', 'episode'] if title.get('kind') == 'episode' else ['title', 'genres', 'plot', 'rating', 'cast']

    formatted_fields = []
    # Hide link for cover image so only the image appears
    formatted_cover = '<a href="{0}">&#8204;</a>'.format(title['full-size cover url'])

    title_line = '<b>{0} ({1}) | {2}</b>\n\n'.format(title[bold_fields[0]], title['year'], title['kind'])
    for field in bold_fields[1:]:
        line = '<b>{0}:</b> {1}'.format(field.title(), title.get(field, 'N/A'))  # Use .get() for safety
        formatted_fields.append(line)

    message = title_line + '\n'.join(formatted_fields) + formatted_cover

    return message

class Alert:
    """
    Enable/disable alerts for given IMDb title and return Telegram message.
    """

    def __init__(self, db_location):
        """
        Initialize database and create alerts table.
        """
        self.db_api = db.Database(db_location)
        self.imdb_api = ia  # Use Cinemagoer instance

    def __del__(self):
        self.db_api.close()

    @_catch_and_log
    def create_db(self):
        """
        Create database and table.
        """
        self.db_api.create_table()


    @_catch_and_log
    def _get_movie_release_date(self, user_id, user_name, title_id, title_name):
        """
        Get movie release date and update database if not yet released
        """

        result = self.imdb_api.get_movie_release_info(title_id)
        release_dates = result['data'].get('raw release dates')
        # regex to check release date string as to avoid datetime.strptime error
        date_regex = r'\d{1,2}\s\w{3,9}\s\d{4}'

        if release_dates:

            usa_release_date = [i['date'] for i in release_dates
                                if i['country'] == 'USA\n'
                                and not i.get('notes')]
            if usa_release_date and match(date_regex, usa_release_date[0]):

                release_date = datetime.strptime(usa_release_date[0], '%d %B %Y')
                if release_date > datetime.now():
                # if the title is not out yet, store it in the database
                    db_values = (user_id, user_name, title_id,
                                 title_name, None, release_date)
                    message = self.db_api.insert(db_values)
                else:
                    message = 'Released on {0} in USA'.format(usa_release_date[0])
            else:
                message = 'Unable to find USA release date'
        else:
            message = 'No release date found'
        return message


    @_catch_and_log
    def _get_episode_release_date(self, user_id, user_name, title_id, title_name):
        """
        Get release date of next episode and update database if not yet released
	"""

        # Get all episodes for title from IMDb
        result = self.imdb_api.get_movie_episodes(title_id)
        title_episodes = result['data'].get('episodes')
        # regex to check release date string as to avoid datetime.strptime error
        date_regex = r'\d{1,2}\s\w{3}.{0,1}\s\d{4}'

        if title_episodes:
            current_season = next(iter(title_episodes))
            latest_episodes = title_episodes[current_season]
            for ep_no, ep_data in latest_episodes.items():
                ep_release_date = ep_data.get('original air date')
                if ep_release_date and match(date_regex, ep_release_date):
                    ep_release_date = ep_release_date.replace('.', '')
                    release_date = datetime.strptime(ep_release_date, '%d %b %Y')
                    if release_date < datetime.now():
                        if ep_no == len(latest_episodes):
                            message = 'Season {0} finale aired' \
                                      ' {1}'.format(current_season, ep_release_date)
                            return message
                    else:
                        # store it in the database
                        title_episode = ep_data.getID()
                        db_values = (user_id, user_name, title_id,
                                     title_name, title_episode, release_date)
                        message = self.db_api.insert(db_values)
                        return message
                else:
                    message = 'Unable to get episode release date'
        else:
            message = 'Unable to get series episodes'

        return message


    @_catch_and_log
    def _update_episode(self, user_id, title_id, current_episode_data):
        """
        Get next episode ID and release date and update the database
        """

        date_regex = r'\d{1,2}\s\w{3}.{0,1}\s\d{4}'
        next_episode_id = current_episode_data.get('next episode')

        if next_episode_id:
            next_episode_data = self.imdb_api.get_episode(next_episode_id)
            next_release_date = next_episode_data.get('original air date')
            if next_release_date and match(date_regex, next_release_date):
            # next episode with valid release date found, store in database
                next_release_date = next_release_date.replace(',', '')
                release_date = datetime.strptime(next_release_date, '%d %b %Y')
            else:
            # no release date for next episode, check again next week
                next_week_date = datetime.now() + timedelta(days=7)
                release_date = next_week_date.replace(hour=0, minute=0,
                                                      second=0, microsecond=0)
                next_episode_id = current_episode_data.getID()

            db_values = (next_episode_id, release_date, user_id, title_id)
            self.db_api.update(db_values)
        else:
            # no next episode not found, assume series ended and remove alert
            self.db_api.delete(user_id, title_id)

        return next_episode_id


    @_catch_and_log
    def enable(self, user_id, user_name, title_id):
        """
        Get movie/series IMDb data and check release date
        """

        imdb_data = self.imdb_api.get_movie(title_id, info=('main'))
        title_name = imdb_data.get('long imdb title')
        seasons = imdb_data.get('seasons')

        if seasons:
            message = self._get_episode_release_date(user_id, user_name,
                                                     title_id, title_name)
        else:
            message = self._get_movie_release_date(user_id, user_name,
                                                   title_id, title_name)
        return message


    @_catch_and_log
    def disable(self, user_id, title_id):
        """
        Remove user's alert from database
        """

        message = self.db_api.delete(user_id, title_id)
        return message


    @_catch_and_log
    def title_name(self, user_id):
        """
        Return string of user's alert title names from the database
        """

        results = self.db_api.query_title_name(user_id)

        if not results:
            message = 'No alerts enabled.\n\n' \
                      'Type /help for info on enabling alerts.'
        elif isinstance(results, list):
            message = '<b>Alerts enabled for:</b>\n\n' + '\n'.join(results)
        else:
            message = results

        return message


    @_catch_and_log
    def title_id(self, user_id):
        """
        Return list of user's title IDs from the database
        """

        results = self.db_api.query_title_id(user_id)
        return results


    @_catch_and_log
    def notify(self):
        """
        Update database entry with next episode ID and release date and
        return a list of alerts to send to users
        """

        alerts = []
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        rows = self.db_api.query_released(today)

        if isinstance(rows, list) and rows:
            for row in rows:
                user_id, title_id, title_episode_id = row[0], row[1], row[2]
                if title_episode_id:
                    current_episode = self.imdb_api.get_episode(title_episode_id)
                    current_release = current_episode['original air date'].replace(',', '')
                    current_release_date = datetime.strptime(current_release, '%d %b %Y')
                    next_episode_id = self._update_episode(user_id, title_id, current_episode)
                    if not next_episode_id:
                        # no next episode found, disable alert
                        fields = get_fields(current_episode)
                        message = 'Series finale episode!' \
                                  '(alert disabled)\n\n' + reply_message(fields)
                        alerts.append((user_id, message))
                    elif current_release_date == today:
                        # do not notify multiple times for the same episode as some
                        # episodes are kept pending their next episode release date
                        fields = get_fields(current_episode)
                        message = 'Episode is out!!\n\n' + reply_message(fields)
                        alerts.append((user_id, message))
                else:
                    # movie has been release, disable alert
                    title_data = self.imdb_api.get_movie(title_id)
                    fields = get_fields(title_data)
                    movie_details = reply_message(fields)
                    message = 'Movie is out!\n\n' + movie_details
                    self.db_api.delete(user_id, title_id)
                    alerts.append((user_id, message))

        return alerts
