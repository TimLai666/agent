import yfinance as yf
from pydantic_ai import Agent

from internal.logger import logger


def add_stock_market_tools(agent: Agent) -> None:
    """Add stock market tools to the agent."""

    @agent.tool_plain
    def get_current_stock_price(ticker_symbol: str, is_taiwan_stock: bool) -> str:
        """
        Get the current stock price for a given ticker symbol.
        Search for the ticker symbol before using it.

        Parameters:
            - ticker_symbol:
            The stock ticker symbol (e.g., "AAPL" for Apple Inc.). For Taiwan stocks, use the format "XXXX.TW".
            - is_taiwan_stock:
            A boolean indicating whether the ticker symbol is for a Taiwan stock.
        Returns:
            - A string indicating the current stock price or an error message if the ticker is invalid.
        """

        # 確保加上 ".TW" 後綴
        if is_taiwan_stock and not ticker_symbol.endswith(".TW"):
            ticker_symbol = ticker_symbol + ".TW"
        logger.info(f"Fetching stock price for ticker: {ticker_symbol}")
        try:
            stock = yf.Ticker(ticker_symbol)
            price = stock.history(period="1d")['Close'].iloc[-1]
            return f"The current price of {ticker_symbol} is {price:.2f}."
        except Exception as e:
            return f"Error fetching stock price: {str(e)}"

    @agent.tool_plain
    def get_stock_history(ticker_symbol: str, period: str = "1mo") -> str:
        """
        Get historical stock data for a given ticker symbol.
        Search for the ticker symbol if you don't know it.

        Parameters:
            - ticker_symbol: 
            The stock ticker symbol (e.g., "AAPL" for Apple Inc.). For Taiwan stocks, use the format "XXXX.TW".
            - period: 
            The period for which to fetch historical data (e.g., "1d", "1mo", "1y"). Use "5d" for 1 week.
        Returns:
            - A string representation of the historical stock data or an error message if the ticker is invalid.
        """
        logger.info(
            f"Fetching historical data for ticker: {ticker_symbol}, period: {period}")
        try:
            stock = yf.Ticker(ticker_symbol)
            history = stock.history(period=period)
            return history.to_string()
        except Exception as e:
            return f"Error fetching stock history: {str(e)}"
