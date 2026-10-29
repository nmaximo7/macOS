from colorama import Fore, Style, init
from util import (
    display_text_color,
    text_horizontalRuler,
    select_quote,
    display_alarm_color,
    stocks,
)
from datetime import datetime
import calendar
import re
import requests
import feedparser
from urllib.parse import quote  # city names with spaces, e.g. "San Francisco"
from myconfig import get_settings  # the ONE place that reads .env


def show_calendar():
    now = datetime.now()
    year, month, day = now.year, now.month, now.day

    cal_str = calendar.month(year, month)

    # day as 2‑wide, to match calendar output (right‑aligned)
    day_str = str(day).rjust(2)

    # regex: match the day as a standalone "cell" (handles leading space)
    pattern = r"(?<!\d)" + re.escape(day_str) + r"(?!\d)"

    # ANSI underline: \033[4m...\033[0m
    highlighted = re.sub(
        pattern,
        f"\033[7m{day_str}\033[0m",
        cal_str,
        count=1,  # only first real occurrence in the grid
    )

    print(highlighted)


def news(max_entries_per_feed=3):
    """Fetch and display the latest news headlines.

    Args:
        max_entries_per_feed (int): Maximum number of entries to display per feed (default: 3)

    Returns:
        None
    """
    # The feed list comes from RSS_FEED_URLS in .env, read by myconfig.py
    try:
        rss_feeds = get_settings().rss_feed_urls
    except ValueError as e:  # a numeric variable elsewhere in .env is invalid
        display_alarm_color(f"Invalid configuration: {e}", Fore.RED)
        return None

    if not rss_feeds:  # RSS_FEED_URLS is missing or empty
        display_alarm_color(
            "No RSS feeds found. Please set the RSS_FEED_URLS variable in .env.",
            Fore.RED,
        )
        return None  # Exit if no RSS feeds are found

    # Display the RSS feeds being used
    display_text_color(f"📡 RSS feeds: {', '.join(rss_feeds)}", Fore.LIGHTBLACK_EX)
    display_text_color(
        f"Fetching top {max_entries_per_feed} news from each feed...", Fore.LIGHTBLACK_EX
    )

    # Loop through the list of RSS feeds
    for feed_url in rss_feeds:
        try:
            # Parse the RSS feed into a structured format
            feed = feedparser.parse(feed_url)

            # Get feed title if available
            feed_title = feed.feed.get("title", feed_url)
            display_text_color(f"\n{'=' * 60}", Fore.CYAN)
            display_text_color(f"📰 {feed_title}", Fore.CYAN)
            display_text_color(f"{'=' * 60}", Fore.CYAN)

            # Limit the number of entries displayed
            entries_to_show = feed.entries[:max_entries_per_feed]

            # Loop through each entry (limited)
            for i, entry in enumerate(entries_to_show, 1):
                # Display the title and link of each news entry
                display_text_color(f"\n{i}. {entry.title}", Fore.YELLOW)
                display_text_color(f"   🔗 {entry.link}", Fore.BLUE)

                # Display the summary if available
                if hasattr(entry, "summary"):
                    # Show a truncated summary if it's longer than 200 characters
                    summary = entry.summary[:200]
                    if len(entry.summary) > 200:
                        summary += "..."
                    display_text_color(f"   {summary}", Fore.WHITE)

            # Show how many total entries are available
            total_entries = len(feed.entries)
            if total_entries > max_entries_per_feed:
                display_text_color(
                    f"   ... and {total_entries - max_entries_per_feed} more entries",
                    Fore.LIGHTBLACK_EX,
                )

        except Exception as e:  # Catch exceptions with error details
            display_alarm_color(f"Failed to fetch {feed_url}: {str(e)}", Fore.RED)


def get_weather(city=None, lang=None):
    """Quick weather check with error handling.

    city / lang: default to WEATHER_CITY / WEATHER_LANG of .env. Without a city,
    wttr.in guesses the place from your IP address.
    """
    try:
        settings = get_settings()
        city = settings.weather_city if city is None else city
        lang = settings.weather_lang if lang is None else lang
    except ValueError as e:  # an invalid number elsewhere in .env
        display_alarm_color(f"Invalid configuration: {e}", Fore.RED)
        return False
    try:
        display_text_color("🌤️  Checking weather...", Fore.CYAN)

        # Format 4: includes condition, temp, wind, humidity
        response = requests.get(
            f"https://wttr.in/{quote(city)}?format=4&lang={quote(lang)}", timeout=5
        )

        if response.status_code == 200:
            display_text_color(response.text.strip(), Fore.MAGENTA)
            return True
        else:
            display_text_color("⚠️  Weather unavailable", Fore.YELLOW)
            return False

    except requests.RequestException:  # no network, timeout, DNS error, ...
        display_text_color("⚠️  Could not fetch weather", Fore.YELLOW)
        return False


def today():
    """Get today's date, display the current month, a quote, weather information,
    news, stocks, and system information.

    Returns:
        None.
    """
    # Get the current date and time
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # Display a horizontal ruler with the current date and time
    text_horizontalRuler(f"Today is {timestamp}")
    # Print the calendar for the current month
    show_calendar()
    # Get a random quote from the quote library
    select_quote()
    get_weather()  # city and language come from .env
    news()
    stocks()


if __name__ == "__main__":
    today()
