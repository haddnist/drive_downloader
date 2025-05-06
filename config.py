# config.py
import logging

# --- Core Settings ---
DOWNLOAD_FOLDER = "downloaded_files"
MAX_WORKERS = 5
LINKS_FILE = "links.txt" # Source of URLs to process if SCRAPE_URL is None

# --- Web Scraping Settings ---
# Set SCRAPE_URL to a specific URL to enable scraping mode.
# If None, the script will use LINKS_FILE.
# Example: SCRAPE_URL = "https://sites.google.com/view/cjin/teaching/ece524"
SCRAPE_URL = None # "https://sites.google.com/view/cjin/teaching/ece524" # << SET YOUR TARGET URL HERE or keep None

# Patterns to identify Google Drive/Docs links when scraping a webpage
# These patterns are designed to find links that are likely GDrive/GDocs files.
# The LinkProcessor will further validate and determine the exact type.
GDOC_LINK_PATTERNS = [
    r"drive\.google\.com/(?:file/d/|open\?id=|uc\?id=)([a-zA-Z0-9_-]+)",
    r"docs\.google\.com/(?:document|spreadsheets|presentation)/d/([a-zA-Z0-9_-]+)"
]

# --- Google Drive Export Defaults ---
DEFAULT_DOC_FORMAT = "pdf"
DEFAULT_SHEET_FORMAT = "xlsx"
DEFAULT_SLIDES_FORMAT = "pptx"

# --- Google Drive Export Choices ---
VALID_DOC_FORMATS = ["pdf", "docx", "odt", "rtf", "txt", "html", "epub"]
VALID_SHEET_FORMATS = ["pdf", "xlsx", "ods", "csv", "tsv", "html"]
VALID_SLIDES_FORMATS = ["pdf", "pptx", "odp", "txt"]

# --- Logging Configuration ---
LOG_LEVEL = logging.INFO
LOG_FORMAT = '%(asctime)s - %(levelname)s - [%(threadName)s] - %(message)s'

# --- Request Settings ---
REQUEST_TIMEOUT = 30
DOWNLOAD_TIMEOUT = 120
CHUNK_SIZE = 8192

# --- User Agent ---
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"