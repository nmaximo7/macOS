from colorama import Fore, Style, init
from datetime import datetime
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
import re  # needed by normalize_string()

# NOTE: the third-party packages `quote` and `yfinance` are NOT imported here.
# They are imported lazily inside select_quote() and stocks(), so that importing
# util.py (and therefore myollama.py and the content_* modules that use it) does
# not require them, and start-up stays fast.

# Initialize colorama for cross-platform colored output
init(autoreset=True)

# Stocks shown by stocks() when STOCK_TICKERS is not set in .env (major US stocks)
DEFAULT_TICKERS = ("AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "BRK-B", "NVDA", "META", "JPM", "V")

# File used by display_message() (only when save_to_file=True) and clear_output_markdown()
OUTPUT_MARKDOWN = "my_output.md"


def normalize_string(s: str) -> str:
    """Helper to normalize string for case and whitespace insensitive comparison.

    Args:
        s (str): The input string to normalize.

    Returns:
        str: A normalized string with reduced whitespace and lowercase letters.
    """
    return re.sub(r"\s+", " ", s).lower()


def display_message(
    text: str, save_to_file: bool = False, filename: str = OUTPUT_MARKDOWN
) -> None:
    """Display a message with a border.

    Args:
        text (str): The message text to display.
        save_to_file (bool): If True, also append the message to a markdown file
            (default False: by default nothing is written to disk).
        filename (str): The markdown file used when save_to_file is True
            (default "my_output.md", relative to the current working directory).

    Returns:
        None
    """
    print(f"\n{Fore.MAGENTA}{'=' * 50}{Style.RESET_ALL}")
    print(f"{Fore.YELLOW}{text}{Style.RESET_ALL}")
    print(f"{Fore.MAGENTA}{'=' * 50}{Style.RESET_ALL}")
    # Append the message to today's file
    # date_str = datetime.now().strftime("%Y-%m-%d")  # e.g. "11-07-2025"
    # filename = f"runs/{date_str}.txt"
    # with open(filename, "a", encoding="utf-8") as f:
    #   f.write(text + "\n")
    if save_to_file:
        with open(filename, "a", encoding="utf-8") as md_file:
            md_file.write(f'<span style="color:yellow;">{text}</span>.')


def print_color(color: str, text: str) -> None:
    """Print text in a specified color.

    Args:
        color (str): The ANSI color code for the text.
        text (str): The text to print.

    Returns:
        None
    """
    print(f"\033[{color}m{text}\033[0m")


def clear_output_markdown(filename: str = OUTPUT_MARKDOWN) -> None:
    """Clear the output markdown file."""
    # Clear the output file
    with open(filename, "w", encoding="utf-8") as md_file:
        # Write an empty string to clear the file
        md_file.write("")


def display_text_color(
    text: str = "Welcome to our CLI Assistant",
    color: str = Fore.GREEN,
    newline: bool = True,
) -> None:
    """Display text in a specified color.

    Args:
        text (str): The text to display.
        color (str): The ANSI color code for the text (default is green).
        newline (bool): If True, print on new line. If False, print inline with space (default is True).

    Returns:
        None
    """
    if newline:
        print(f"{color}{text}{Style.RESET_ALL}")
    else:
        print(f"{color}{text}{Style.RESET_ALL}", end=" ")


def display_alarm_color(text: str, color: str = Fore.RED, emoji: str = "⚠️") -> None:
    """Display an alarm message in a specified color, prefixed by an emoji to draw attention.

    Args:
        text (str): The alarm message to display.
        color (str): The ANSI color code for the text (default is red).
        emoji (str): An emoji to prefix the message (default is warning emoji).

    Returns:
        None
    """
    print(f"{color}{emoji} {text}{Style.RESET_ALL}")


def text_horizontalRuler(text: str = "Welcome to our CLI Assistant") -> None:
    """Display a horizontal ruler with the specified text and color.

    Args:
        text (str): The text to display in the ruler.
        color (str): The ANSI color code for the text (default is green).

    Returns:
        None
    """
    # Create a Console object
    console = Console()
    # Print some text in the specified color
    console.print(text, style="magenta")
    # Print a horizontal ruler
    console.rule()


def select_quote():
    """Print one random quote (with its author) for the daily dashboard.

    Uses `content_quotes` (your fortunes file, the system `fortune`, the quotes library and
    the optional online sources listed in QUOTE_SOURCES), so the dashboard and the page
    tools share one quote engine. `content_quotes` is imported here, not at the top of the
    file, so `util` stays light. If nothing is available a yellow notice is printed.

    Returns:
        None
    """
    from content_quotes import pick_daily_quote

    quote, notes = pick_daily_quote()
    if quote is None:
        detail = f" ({notes[0][1]})" if notes else ""
        display_alarm_color(f"No quote today{detail}.", Fore.YELLOW)
        return None
    author = f"\n -- {quote.author}" if quote.author else ""
    display_text_color(f"{quote.text}{author}\n", Fore.CYAN)
    return None


def stocks(tickers=None):
    """Display today's closing prices for a list of stocks.

    tickers: list of symbols; by default STOCK_TICKERS of .env (or ten major US stocks).
    `yfinance` is imported here (not at the top of the file) so that it is only
    required when this function is actually used.
    """
    try:
        import yfinance as yf  # imported lazily: only needed here
    except ImportError:
        display_alarm_color(
            "The 'yfinance' package is not installed (pip install yfinance): no stock prices today.",
            Fore.YELLOW,
        )
        return None

    if tickers is None:
        try:
            from myconfig import get_settings  # lazy: util.py itself does not need .env

            tickers = get_settings().stock_tickers
        except Exception:  # myconfig or .env unusable: fall back to the built-in list
            tickers = DEFAULT_TICKERS
    display_text_color(
        "Fetching today's stock prices...", Fore.LIGHTBLACK_EX
    )  # Indicate fetching process

    # Loop or iterate through the list of stock tickers
    for ticker in tickers:
        # Fetch the stock data using yfinance
        # yfinance is an open-source tool that uses Yahoo's publicly available APIs.
        # It is intended exclusively for research and educational purposes.
        stock = yf.Ticker(ticker)  # Create a Ticker object for the stock
        # Get the historical data for the stock
        # Here we use '1d' to get the latest day's data
        data = stock.history(period="1d")
        if not data.empty:  # Check if the data is not empty (contains data)
            # Get the closing price from the data
            price = data["Close"].iloc[0]
            # Display the ticker and closing price
            display_text_color(f"{ticker}: ${price:.2f}", Fore.CYAN, False)
        else:  # If the data is empty
            # Indicate no data available
            display_text_color(f"{ticker}: No data", Fore.GREEN, False)


def display_log_color(text: str, color: str = Fore.GREEN, level: str = "INFO") -> None:
    """Display a log message with a timestamp, log level, and color for easy scanning.

    Args:
        text (str): The log message to display.
        color (str): The ANSI color code for the text (default is green).
        level (str): The log level (default is "INFO").

    Returns:
        None
    """
    # Get the current timestamp in YYYY-MM-DD HH:MM:SS format
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # Display the log message with a timestamp, log level, and color
    print(f"{color}{timestamp} [{level}] {text}{Style.RESET_ALL}")


def display_chunck(text: str, color: str = Fore.GREEN) -> None:
    """Display text in a specified color without a newline.

    Args:
        text (str): The text to display.
        color (str): The ANSI color code for the text (default is green).

    Returns:
        None
    """
    # Print the text in the specified color without a newline
    print(f"{color}{text}{Style.RESET_ALL}", end="", flush=True)
