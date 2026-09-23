"""
NEWS SCRAPER FOR FINBERT SENTIMENT ANALYSIS v2.0.0
============================================================================

✅ UPDATED: Now includes ALL 150 NSE stocks from your trading universe!

SOURCES (FREE, No API Key Required):
────────────────────────────────────
1. Google News RSS - Primary source (free, no rate limits)
2. Economic Times RSS - Indian market focus
3. Moneycontrol RSS - NSE-specific news

USAGE:
──────
from news_scraper import NewsScraperFree

scraper = NewsScraperFree()

# Get news for a stock
headlines = scraper.get_stock_news("HDFCBANK", max_results=5)
# Returns: ["HDFC Bank posts Q3 profit...", "Analysts bullish on HDFC..."]

# Get general market news  
market_news = scraper.get_market_news(max_results=10)

Author: Claude + Dheebanraj
Date: January 2026
Version: 2.0.0 - 150 Stock Universe!
"""

import feedparser
import logging
import time
import urllib.parse
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from functools import lru_cache
import re

logger = logging.getLogger('NewsScraper')


# ═══════════════════════════════════════════════════════════════════════════
# 📊 COMPLETE 150 STOCK UNIVERSE (Mapped to Company Names)
# ═══════════════════════════════════════════════════════════════════════════

STOCK_NAME_MAP = {
    # ════════════════════════════════════════════════════════════════════════
    # IT SECTOR (6 stocks)
    # ════════════════════════════════════════════════════════════════════════
    'INFY': 'Infosys',
    'TCS': 'TCS Tata Consultancy Services',
    'WIPRO': 'Wipro',
    'HCLTECH': 'HCL Technologies',
    'TECHM': 'Tech Mahindra',
    'LTIM': 'LTIMindtree',
    'MPHASIS': 'Mphasis',
    'COFORGE': 'Coforge',
    'PERSISTENT': 'Persistent Systems',
    'LTTS': 'L&T Technology Services',
    
    # ════════════════════════════════════════════════════════════════════════
    # BANKING - PRIVATE (6 stocks)
    # ════════════════════════════════════════════════════════════════════════
    'HDFCBANK': 'HDFC Bank',
    'ICICIBANK': 'ICICI Bank',
    'KOTAKBANK': 'Kotak Mahindra Bank',
    'AXISBANK': 'Axis Bank',
    'INDUSINDBK': 'IndusInd Bank',
    'FEDERALBNK': 'Federal Bank',
    'IDFCFIRSTB': 'IDFC First Bank',
    'BANDHANBNK': 'Bandhan Bank',
    'RBLBANK': 'RBL Bank',
    
    # ════════════════════════════════════════════════════════════════════════
    # PSU BANKS (4 stocks)
    # ════════════════════════════════════════════════════════════════════════
    'SBIN': 'State Bank of India SBI',
    'BANKBARODA': 'Bank of Baroda',
    'PNB': 'Punjab National Bank',
    'CANBK': 'Canara Bank',
    'UNIONBANK': 'Union Bank of India',
    'INDIANB': 'Indian Bank',
    'IOB': 'Indian Overseas Bank',
    'BANKINDIA': 'Bank of India',
    'MAHABANK': 'Bank of Maharashtra',
    
    # ════════════════════════════════════════════════════════════════════════
    # FINANCE - NBFC (6 stocks)
    # ════════════════════════════════════════════════════════════════════════
    'BAJFINANCE': 'Bajaj Finance',
    'BAJAJFINSV': 'Bajaj Finserv',
    'HDFC': 'HDFC Limited',
    'CHOLAFIN': 'Cholamandalam Finance',
    'MUTHOOTFIN': 'Muthoot Finance',
    'MANAPPURAM': 'Manappuram Finance',
    'SHRIRAMFIN': 'Shriram Finance',
    'M&MFIN': 'Mahindra Finance',
    'LICHSGFIN': 'LIC Housing Finance',
    'POONAWALLA': 'Poonawalla Fincorp',
    'SBICARD': 'SBI Cards',
    
    # ════════════════════════════════════════════════════════════════════════
    # PHARMA (6 stocks)
    # ════════════════════════════════════════════════════════════════════════
    'SUNPHARMA': 'Sun Pharma',
    'DRREDDY': 'Dr Reddys Laboratories',
    'CIPLA': 'Cipla',
    'DIVISLAB': 'Divis Laboratories',
    'AUROPHARMA': 'Aurobindo Pharma',
    'BIOCON': 'Biocon',
    'LUPIN': 'Lupin',
    'TORNTPHARM': 'Torrent Pharma',
    'ALKEM': 'Alkem Laboratories',
    'GLENMARK': 'Glenmark Pharma',
    'LAURUSLABS': 'Laurus Labs',
    'ZYDUSLIFE': 'Zydus Lifesciences',
    
    # ════════════════════════════════════════════════════════════════════════
    # AUTO (6 stocks)
    # ════════════════════════════════════════════════════════════════════════
    'MARUTI': 'Maruti Suzuki',
    'TATAMOTORS': 'Tata Motors',
    'M&M': 'Mahindra Mahindra',
    'HEROMOTOCO': 'Hero MotoCorp',
    'BAJAJ-AUTO': 'Bajaj Auto',
    'EICHERMOT': 'Eicher Motors Royal Enfield',
    'ASHOKLEY': 'Ashok Leyland',
    'TVSMOTOR': 'TVS Motor',
    'BHARATFORG': 'Bharat Forge',
    'MOTHERSON': 'Motherson Sumi',
    'BOSCHLTD': 'Bosch',
    'MRF': 'MRF Tyres',
    'APOLLOTYRE': 'Apollo Tyres',
    'EXIDEIND': 'Exide Industries',
    'BALKRISIND': 'Balkrishna Industries',
    
    # ════════════════════════════════════════════════════════════════════════
    # FMCG (6 stocks)
    # ════════════════════════════════════════════════════════════════════════
    'HINDUNILVR': 'Hindustan Unilever HUL',
    'ITC': 'ITC Limited',
    'NESTLEIND': 'Nestle India',
    'BRITANNIA': 'Britannia Industries',
    'DABUR': 'Dabur India',
    'MARICO': 'Marico',
    'GODREJCP': 'Godrej Consumer Products',
    'COLPAL': 'Colgate Palmolive',
    'TATACONSUM': 'Tata Consumer Products',
    'VBL': 'Varun Beverages',
    'UBL': 'United Breweries',
    'MCDOWELL-N': 'United Spirits McDowell',
    'EMAMILTD': 'Emami',
    
    # ════════════════════════════════════════════════════════════════════════
    # METALS (6 stocks)
    # ════════════════════════════════════════════════════════════════════════
    'TATASTEEL': 'Tata Steel',
    'JSWSTEEL': 'JSW Steel',
    'HINDALCO': 'Hindalco Novelis',
    'VEDL': 'Vedanta',
    'SAIL': 'SAIL Steel Authority',
    'NMDC': 'NMDC Iron Ore',
    'COALINDIA': 'Coal India',
    'JINDALSTEL': 'Jindal Steel Power',
    'NATIONALUM': 'National Aluminium NALCO',
    'HINDZINC': 'Hindustan Zinc',
    'MOIL': 'MOIL Manganese',
    'APLAPOLLO': 'APL Apollo Tubes',
    
    # ════════════════════════════════════════════════════════════════════════
    # ENERGY / OIL & GAS (10 stocks)
    # ════════════════════════════════════════════════════════════════════════
    'RELIANCE': 'Reliance Industries',
    'ONGC': 'ONGC Oil Natural Gas',
    'IOC': 'Indian Oil Corporation',
    'BPCL': 'Bharat Petroleum BPCL',
    'GAIL': 'GAIL India Gas',
    'NTPC': 'NTPC Power',
    'POWERGRID': 'Power Grid Corporation',
    'ADANIGREEN': 'Adani Green Energy',
    'ADANIPOWER': 'Adani Power',
    'TATAPOWER': 'Tata Power',
    'TORNTPOWER': 'Torrent Power',
    'NHPC': 'NHPC Hydro Power',
    'SJVN': 'SJVN Power',
    'IGL': 'Indraprastha Gas IGL',
    'MGL': 'Mahanagar Gas',
    'PETRONET': 'Petronet LNG',
    'OIL': 'Oil India',
    'HINDPETRO': 'HPCL Hindustan Petroleum',
    'MRPL': 'MRPL Mangalore Refinery',
    
    # ════════════════════════════════════════════════════════════════════════
    # REALTY (4 stocks)
    # ════════════════════════════════════════════════════════════════════════
    'DLF': 'DLF Realty',
    'GODREJPROP': 'Godrej Properties',
    'OBEROIRLTY': 'Oberoi Realty',
    'PRESTIGE': 'Prestige Estates',
    'BRIGADE': 'Brigade Enterprises',
    'SOBHA': 'Sobha Limited',
    'PHOENIXLTD': 'Phoenix Mills',
    'LODHA': 'Macrotech Developers Lodha',
    
    # ════════════════════════════════════════════════════════════════════════
    # INFRASTRUCTURE (4 stocks)
    # ════════════════════════════════════════════════════════════════════════
    'LT': 'Larsen Toubro L&T',
    'ADANIENT': 'Adani Enterprises',
    'ADANIPORTS': 'Adani Ports SEZ',
    'IRB': 'IRB Infra',
    'GMRINFRA': 'GMR Infrastructure',
    'NBCC': 'NBCC India',
    'ENGINERSIN': 'Engineers India',
    'BEL': 'Bharat Electronics BEL',
    'HAL': 'Hindustan Aeronautics HAL',
    'BHEL': 'BHEL Heavy Electricals',
    'IRCON': 'IRCON International',
    'RVNL': 'Rail Vikas Nigam RVNL',
    
    # ════════════════════════════════════════════════════════════════════════
    # CONSUMER DURABLES (4 stocks)
    # ════════════════════════════════════════════════════════════════════════
    'TITAN': 'Titan Company Tanishq',
    'HAVELLS': 'Havells India',
    'VOLTAS': 'Voltas Tata',
    'BLUESTARCO': 'Blue Star',
    'WHIRLPOOL': 'Whirlpool India',
    'CROMPTON': 'Crompton Greaves Consumer',
    'KAJARIACER': 'Kajaria Ceramics',
    'BATAINDIA': 'Bata India',
    'PAGEIND': 'Page Industries Jockey',
    'RELAXO': 'Relaxo Footwears',
    'RAJESHEXPO': 'Rajesh Exports',
    'KALYANJEWE': 'Kalyan Jewellers',
    
    # ════════════════════════════════════════════════════════════════════════
    # HEALTHCARE (4 stocks)
    # ════════════════════════════════════════════════════════════════════════
    'APOLLOHOSP': 'Apollo Hospitals',
    'FORTIS': 'Fortis Healthcare',
    'MAXHEALTH': 'Max Healthcare',
    'METROPOLIS': 'Metropolis Healthcare',
    'LALPATHLAB': 'Dr Lal PathLabs',
    'THYROCARE': 'Thyrocare Technologies',
    'SYNGENE': 'Syngene International',
    'GLAND': 'Gland Pharma',
    
    # ════════════════════════════════════════════════════════════════════════
    # DIVERSIFIED / CEMENT (4 stocks)
    # ════════════════════════════════════════════════════════════════════════
    'ASIANPAINT': 'Asian Paints',
    'ULTRACEMCO': 'UltraTech Cement',
    'GRASIM': 'Grasim Industries',
    'AMBUJACEM': 'Ambuja Cements',
    'ACC': 'ACC Cement',
    'SHREECEM': 'Shree Cement',
    'RAMCOCEM': 'Ramco Cements',
    'JKCEMENT': 'JK Cement',
    'DALMIACEM': 'Dalmia Bharat Cement',
    'INDIACEM': 'India Cements',
    'BERGEPAINT': 'Berger Paints',
    'PIDILITIND': 'Pidilite Industries Fevicol',
    
    # ════════════════════════════════════════════════════════════════════════
    # TELECOM (3 stocks)
    # ════════════════════════════════════════════════════════════════════════
    'BHARTIARTL': 'Bharti Airtel',
    'IDEA': 'Vodafone Idea VI',
    'INDUSTOWER': 'Indus Towers',
    'TATACOMM': 'Tata Communications',
    
    # ════════════════════════════════════════════════════════════════════════
    # INSURANCE (4 stocks)
    # ════════════════════════════════════════════════════════════════════════
    'SBILIFE': 'SBI Life Insurance',
    'HDFCLIFE': 'HDFC Life Insurance',
    'ICICIGI': 'ICICI Lombard General Insurance',
    'ICICIPRULI': 'ICICI Prudential Life',
    'LICI': 'LIC India',
    'GICRE': 'GIC Reinsurance',
    'NIACL': 'New India Assurance',
    'STARHEALTH': 'Star Health Insurance',
    
    # ════════════════════════════════════════════════════════════════════════
    # NEW AGE / TECH / E-COMMERCE (8 stocks)
    # ════════════════════════════════════════════════════════════════════════
    'ZOMATO': 'Zomato Food Delivery',
    'PAYTM': 'Paytm One97 Communications',
    'NYKAA': 'FSN E-Commerce Nykaa',
    'DMART': 'Avenue Supermarts DMart',
    'TRENT': 'Trent Westside Zudio',
    'IRCTC': 'IRCTC Railways Catering',
    'POLICYBZR': 'PB Fintech PolicyBazaar',
    'CARTRADE': 'CarTrade Tech',
    'EASEMYTRIP': 'Easy Trip Planners',
    'INDIAMART': 'IndiaMART InterMESH',
    
    # ════════════════════════════════════════════════════════════════════════
    # DEFENSE / RAILWAYS (4 stocks)
    # ════════════════════════════════════════════════════════════════════════
    'HAL': 'Hindustan Aeronautics HAL Defence',
    'BEL': 'Bharat Electronics BEL Defence',
    'COCHINSHIP': 'Cochin Shipyard',
    'MAZAGON': 'Mazagon Dock Shipbuilders',
    'GRSE': 'Garden Reach Shipbuilders',
    'BDL': 'Bharat Dynamics',
    'IRFC': 'Indian Railway Finance',
    'RAILTEL': 'RailTel Corporation',
    'TIINDIA': 'Tube Investments',
    
    # ════════════════════════════════════════════════════════════════════════
    # CHEMICALS / SPECIALTY (6 stocks)
    # ════════════════════════════════════════════════════════════════════════
    'PIIND': 'PI Industries',
    'SRF': 'SRF Limited',
    'ATUL': 'Atul Limited',
    'DEEPAKNTR': 'Deepak Nitrite',
    'NAVINFLUOR': 'Navin Fluorine',
    'FLUOROCHEM': 'Gujarat Fluorochemicals',
    'CLEAN': 'Clean Science Technology',
    'TATACHEM': 'Tata Chemicals',
    'GNFC': 'Gujarat Narmada Fertilizers',
    'CHAMBERLIN': 'Chambal Fertilizers',
    'COROMANDEL': 'Coromandel International',
    'UPL': 'UPL Limited Agrochemicals',
    
    # ════════════════════════════════════════════════════════════════════════
    # OTHERS / MISCELLANEOUS
    # ════════════════════════════════════════════════════════════════════════
    'SIEMENS': 'Siemens India',
    'ABB': 'ABB India',
    'CUMMINSIND': 'Cummins India',
    'THERMAX': 'Thermax',
    'AIAENG': 'AIA Engineering',
    'GRINDWELL': 'Grindwell Norton',
    'HONAUT': 'Honeywell Automation',
    'SUNTV': 'Sun TV Network',
    'ZEEL': 'Zee Entertainment',
    'PVR': 'PVR INOX',
    'PVRINOX': 'PVR INOX',
    'ABCAPITAL': 'Aditya Birla Capital',
    'MFSL': 'Max Financial Services',
    'IIFL': 'IIFL Finance',
    'JBCHEPHARM': 'JB Chemicals',
    'NATCOPHARM': 'Natco Pharma',
    'GRANULES': 'Granules India',
    'AFFLE': 'Affle India',
    'TANLA': 'Tanla Platforms',
    'ROUTE': 'Route Mobile',
    'HAPPSTMNDS': 'Happiest Minds',
    'KPITTECH': 'KPIT Technologies',
    'TATAELXSI': 'Tata Elxsi',
    'MINDTREE': 'LTIMindtree',
    'CYIENT': 'Cyient',
    'ZENSAR': 'Zensar Technologies',
    'OFSS': 'Oracle Financial OFSS',
    'SONATSOFTW': 'Sonata Software',
    'BSOFT': 'Birlasoft',
}

# Sector mapping for filtering
STOCK_SECTOR_MAP = {
    'INFY': 'IT', 'TCS': 'IT', 'WIPRO': 'IT', 'HCLTECH': 'IT', 'TECHM': 'IT', 'LTIM': 'IT',
    'HDFCBANK': 'BANKING', 'ICICIBANK': 'BANKING', 'KOTAKBANK': 'BANKING', 'AXISBANK': 'BANKING',
    'SBIN': 'PSU BANK', 'BANKBARODA': 'PSU BANK', 'PNB': 'PSU BANK', 'CANBK': 'PSU BANK',
    'BAJFINANCE': 'FINANCE', 'BAJAJFINSV': 'FINANCE', 'HDFC': 'FINANCE',
    'SUNPHARMA': 'PHARMA', 'DRREDDY': 'PHARMA', 'CIPLA': 'PHARMA', 'DIVISLAB': 'PHARMA',
    'MARUTI': 'AUTO', 'TATAMOTORS': 'AUTO', 'M&M': 'AUTO', 'HEROMOTOCO': 'AUTO', 'BAJAJ-AUTO': 'AUTO',
    'HINDUNILVR': 'FMCG', 'ITC': 'FMCG', 'NESTLEIND': 'FMCG', 'BRITANNIA': 'FMCG', 'DABUR': 'FMCG',
    'TATASTEEL': 'METAL', 'JSWSTEEL': 'METAL', 'HINDALCO': 'METAL', 'VEDL': 'METAL',
    'RELIANCE': 'ENERGY', 'ONGC': 'ENERGY', 'IOC': 'ENERGY', 'BPCL': 'ENERGY', 'GAIL': 'ENERGY',
    'NTPC': 'ENERGY', 'POWERGRID': 'ENERGY', 'ADANIGREEN': 'ENERGY', 'ADANIPOWER': 'ENERGY',
    'DLF': 'REALTY', 'GODREJPROP': 'REALTY', 'OBEROIRLTY': 'REALTY',
    'LT': 'INFRASTRUCTURE', 'ADANIENT': 'INFRASTRUCTURE', 'ADANIPORTS': 'INFRASTRUCTURE',
    'TITAN': 'CONSUMER DURABLES', 'HAVELLS': 'CONSUMER DURABLES', 'VOLTAS': 'CONSUMER DURABLES',
    'APOLLOHOSP': 'HEALTHCARE', 'FORTIS': 'HEALTHCARE', 'MAXHEALTH': 'HEALTHCARE',
    'ASIANPAINT': 'DIVERSIFIED', 'ULTRACEMCO': 'DIVERSIFIED', 'GRASIM': 'DIVERSIFIED',
}


class NewsScraperFree:
    """
    Free news scraper using RSS feeds (no API key required).
    
    Provides news headlines for FinBERT sentiment analysis.
    Uses Google News RSS + Indian financial news sources.
    """
    
    # RSS Feed URLs
    GOOGLE_NEWS_RSS = "https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"
    ET_MARKETS_RSS = "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"
    MONEYCONTROL_RSS = "https://www.moneycontrol.com/rss/marketreports.xml"
    
    def __init__(self, cache_minutes: int = 5, rate_limit_seconds: float = 1.0):
        """
        Initialize news scraper.
        
        Args:
            cache_minutes: Cache duration in minutes (default 5)
            rate_limit_seconds: Delay between requests (default 1.0)
        """
        self.cache = {}
        self.cache_duration = timedelta(minutes=cache_minutes)
        self.rate_limit_seconds = rate_limit_seconds
        self.last_request_time = None
        
        # Use the global stock name map
        self.stock_name_map = STOCK_NAME_MAP
        self.stock_sector_map = STOCK_SECTOR_MAP
        
        logger.info(f"NewsScraperFree initialized")
        logger.info(f"  Stock mappings: {len(self.stock_name_map)} stocks")
        logger.info(f"  Cache duration: {cache_minutes} minutes")
        logger.info(f"  Rate limit: {rate_limit_seconds}s between requests")
    
    def _rate_limit(self):
        """Enforce rate limiting between requests"""
        if self.last_request_time:
            elapsed = (datetime.now() - self.last_request_time).total_seconds()
            if elapsed < self.rate_limit_seconds:
                time.sleep(self.rate_limit_seconds - elapsed)
        self.last_request_time = datetime.now()
    
    def _get_search_term(self, symbol: str) -> str:
        """
        Get search term for stock symbol.
        
        Args:
            symbol: Stock symbol (e.g., 'HDFCBANK')
            
        Returns:
            Search term (e.g., 'HDFC Bank stock NSE')
        """
        company_name = self.stock_name_map.get(symbol, symbol)
        return f"{company_name} stock NSE"
    
    def _check_cache(self, key: str) -> Optional[List[str]]:
        """Check if cached data is still valid"""
        if key in self.cache:
            cached_time, cached_data = self.cache[key]
            if datetime.now() - cached_time < self.cache_duration:
                logger.debug(f"Cache hit for {key}")
                return cached_data
        return None
    
    def _update_cache(self, key: str, data: List[str]):
        """Update cache with new data"""
        self.cache[key] = (datetime.now(), data)
    
    def get_stock_news(self, symbol: str, max_results: int = 5) -> List[str]:
        """
        Get news headlines for a stock.
        
        Args:
            symbol: Stock symbol (e.g., 'HDFCBANK')
            max_results: Maximum headlines to return
            
        Returns:
            List of headline strings
        """
        # Check cache first
        cached = self._check_cache(f"stock_{symbol}")
        if cached:
            return cached[:max_results]
        
        # Rate limiting
        self._rate_limit()
        
        # Get search term
        search_term = self._get_search_term(symbol)
        
        # Fetch from Google News
        headlines = self._fetch_google_news(search_term, max_results)
        
        # Update cache
        if headlines:
            self._update_cache(f"stock_{symbol}", headlines)
            logger.info(f"Fetched {len(headlines)} headlines for {symbol}")
        else:
            logger.warning(f"No headlines found for {symbol}")
        
        return headlines
    
    def _fetch_google_news(self, query: str, max_results: int = 5) -> List[str]:
        """
        Fetch news from Google News RSS.
        
        Args:
            query: Search query
            max_results: Max results to return
            
        Returns:
            List of headline strings
        """
        try:
            # Encode query for URL
            encoded_query = urllib.parse.quote(query)
            url = self.GOOGLE_NEWS_RSS.format(query=encoded_query)
            
            # Parse RSS feed
            feed = feedparser.parse(url)
            
            headlines = []
            for entry in feed.entries[:max_results]:
                # Clean title (remove source suffix like " - Economic Times")
                title = entry.title
                if ' - ' in title:
                    title = title.rsplit(' - ', 1)[0]
                
                headlines.append(title.strip())
            
            return headlines
            
        except Exception as e:
            logger.error(f"Google News fetch error: {e}")
            return []
    
    def get_market_news(self, max_results: int = 10) -> List[str]:
        """
        Get general market news.
        
        Args:
            max_results: Maximum headlines to return
            
        Returns:
            List of headline strings
        """
        # Check cache
        cached = self._check_cache("market_news")
        if cached:
            return cached[:max_results]
        
        self._rate_limit()
        
        headlines = []
        
        # Fetch from multiple sources
        try:
            # Google News - Indian Markets
            google_headlines = self._fetch_google_news("NSE Nifty stock market India", 5)
            headlines.extend(google_headlines)
            
            # Economic Times RSS
            et_headlines = self._fetch_rss_feed(self.ET_MARKETS_RSS, 5)
            headlines.extend(et_headlines)
            
        except Exception as e:
            logger.error(f"Market news fetch error: {e}")
        
        # Remove duplicates while preserving order
        seen = set()
        unique_headlines = []
        for h in headlines:
            if h.lower() not in seen:
                seen.add(h.lower())
                unique_headlines.append(h)
        
        # Update cache
        if unique_headlines:
            self._update_cache("market_news", unique_headlines)
        
        return unique_headlines[:max_results]
    
    def _fetch_rss_feed(self, url: str, max_results: int = 5) -> List[str]:
        """
        Fetch headlines from any RSS feed.
        
        Args:
            url: RSS feed URL
            max_results: Max results
            
        Returns:
            List of headline strings
        """
        try:
            feed = feedparser.parse(url)
            
            headlines = []
            for entry in feed.entries[:max_results]:
                title = entry.title.strip()
                # Clean up HTML entities
                title = title.replace('&amp;', '&')
                title = title.replace('&quot;', '"')
                headlines.append(title)
            
            return headlines
            
        except Exception as e:
            logger.error(f"RSS fetch error for {url}: {e}")
            return []
    
    def get_sector_news(self, sector: str, max_results: int = 5) -> List[str]:
        """
        Get news for a specific sector.
        
        Args:
            sector: Sector name (e.g., 'BANKING', 'IT', 'PHARMA')
            max_results: Maximum headlines
            
        Returns:
            List of headline strings
        """
        sector_queries = {
            'IT': 'Indian IT sector TCS Infosys',
            'BANKING': 'Indian banking sector HDFC Bank ICICI',
            'PSU BANK': 'Indian PSU banks SBI PNB',
            'FINANCE': 'Indian NBFC finance Bajaj Finance',
            'PHARMA': 'Indian pharma sector Sun Pharma Cipla',
            'AUTO': 'Indian auto sector Maruti Tata Motors',
            'FMCG': 'Indian FMCG sector HUL ITC',
            'METAL': 'Indian metal sector Tata Steel JSW',
            'ENERGY': 'Indian energy sector Reliance ONGC',
            'REALTY': 'Indian real estate sector DLF Godrej',
            'INFRASTRUCTURE': 'Indian infra sector L&T Adani',
            'CONSUMER DURABLES': 'Indian consumer durables Titan Havells',
            'HEALTHCARE': 'Indian healthcare Apollo Fortis',
            'DIVERSIFIED': 'Indian diversified sector Asian Paints',
        }
        
        query = sector_queries.get(sector.upper(), f"Indian {sector} sector stock")
        
        # Check cache
        cached = self._check_cache(f"sector_{sector}")
        if cached:
            return cached[:max_results]
        
        self._rate_limit()
        
        headlines = self._fetch_google_news(query, max_results)
        
        if headlines:
            self._update_cache(f"sector_{sector}", headlines)
        
        return headlines
    
    def get_stock_with_sector_news(self, symbol: str, max_results: int = 5) -> Dict:
        """
        Get both stock-specific and sector news.
        
        Args:
            symbol: Stock symbol
            max_results: Max headlines per category
            
        Returns:
            {
                'stock_news': [...],
                'sector_news': [...],
                'sector': 'BANKING',
                'combined': [...]  # For FinBERT
            }
        """
        stock_news = self.get_stock_news(symbol, max_results)
        
        sector = self.stock_sector_map.get(symbol, 'DIVERSIFIED')
        sector_news = self.get_sector_news(sector, max_results)
        
        # Combine for FinBERT (stock news has higher weight)
        combined = stock_news[:3] + sector_news[:2]
        
        return {
            'stock_news': stock_news,
            'sector_news': sector_news,
            'sector': sector,
            'combined': combined
        }
    
    def clear_cache(self):
        """Clear all cached data"""
        self.cache.clear()
        logger.info("News cache cleared")
    
    def get_cache_stats(self) -> Dict:
        """Get cache statistics"""
        now = datetime.now()
        active = 0
        expired = 0
        
        for key, (cached_time, _) in self.cache.items():
            if now - cached_time < self.cache_duration:
                active += 1
            else:
                expired += 1
        
        return {
            'total': len(self.cache),
            'active': active,
            'expired': expired,
            'stocks_mapped': len(self.stock_name_map)
        }


# ═══════════════════════════════════════════════════════════════════════════
# STANDALONE TESTING
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    print("=" * 70)
    print("NEWS SCRAPER v2.0.0 - 150 STOCK UNIVERSE TEST")
    print("=" * 70)
    
    scraper = NewsScraperFree()
    
    # Test stocks from different sectors
    test_stocks = ['HDFCBANK', 'INFY', 'RELIANCE', 'TATASTEEL', 'SUNPHARMA', 'MARUTI']
    
    for symbol in test_stocks:
        print(f"\n📰 Headlines for {symbol}:")
        print("-" * 50)
        
        headlines = scraper.get_stock_news(symbol, max_results=3)
        
        if headlines:
            for i, h in enumerate(headlines, 1):
                print(f"  {i}. {h[:70]}...")
        else:
            print("  ❌ No headlines found")
    
    # Test market news
    print(f"\n📊 MARKET NEWS:")
    print("-" * 50)
    market_news = scraper.get_market_news(max_results=5)
    for i, h in enumerate(market_news, 1):
        print(f"  {i}. {h[:70]}...")
    
    # Cache stats
    print(f"\n📈 CACHE STATS:")
    print(scraper.get_cache_stats())
    
    print("\n" + "=" * 70)
    print("✅ Test complete!")
    print("=" * 70)