# link_extractor.py
import os
import re # Ensure re is imported
import logging
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

from config import USER_AGENT

logger = logging.getLogger(__name__)

class LinkExtractor:
    def __init__(self, source_file_path=None):
        self.source_file_path = source_file_path

    def get_links_from_file(self) -> list[str]:
        # ... (no changes here)
        if not self.source_file_path or not os.path.exists(self.source_file_path):
            logger.error(f"Source file '{self.source_file_path}' not found.")
            return []
        try:
            with open(self.source_file_path, "r", encoding="utf-8") as f:
                urls = [line.strip() for line in f if line.strip() and not line.startswith("#")]
            logger.info(f"Found {len(urls)} URLs in '{self.source_file_path}'.")
            return urls
        except Exception as e:
            logger.error(f"Error reading links from '{self.source_file_path}': {e}")
            return []


    def get_links_from_webpage(self, page_url: str, link_patterns: list[str]) -> list[str]:
        """
        Scrapes a webpage for links matching given patterns.
        Args:
            page_url: The URL of the webpage to scrape.
            link_patterns: A list of regex patterns to identify desired links.
        Returns:
            A list of unique URLs found on the page.
        """
        logger.info(f"Attempting to scrape links from: {page_url}")
        try:
            headers = {'User-Agent': USER_AGENT}
            response = requests.get(page_url, headers=headers, timeout=15)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')
            
            found_links = set()
            for a_tag in soup.find_all('a', href=True):
                href = a_tag['href']
                
                # Ignore common non-http links early
                if href.startswith(('javascript:', 'mailto:', 'tel:')):
                    continue

                # Resolve relative URLs
                full_url = urljoin(page_url, href)
                
                # Normalize URL: remove fragment and ensure scheme
                parsed_url = urlparse(full_url)
                if not parsed_url.scheme: # If urljoin resulted in scheme-relative URL like //example.com
                    parsed_page_url = urlparse(page_url)
                    normalized_url = parsed_url._replace(scheme=parsed_page_url.scheme, fragment="").geturl()
                else:
                    normalized_url = parsed_url._replace(fragment="").geturl()
                
                # Check if the link matches any of the provided patterns
                for pattern in link_patterns:
                    if re.search(pattern, normalized_url, re.IGNORECASE):
                        logger.debug(f"Scraper found matching link: {normalized_url} (Pattern: {pattern})")
                        found_links.add(normalized_url)
                        break # Matched one pattern
            
            logger.info(f"Found {len(found_links)} unique links matching patterns on {page_url}.")
            return list(found_links)
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching webpage {page_url}: {e}")
        except Exception as e:
            logger.error(f"An unexpected error occurred while scraping {page_url}: {e}")
        return []

# ... (rest of the file, example usage if any)
# Example usage (can be removed or kept for testing this module)
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
    
    # Test file extraction
    # Create a dummy links.txt
    dummy_links_file = "dummy_links.txt"
    with open(dummy_links_file, "w") as f:
        f.write("https://drive.google.com/file/d/FILE_ID_1/view\n")
        f.write("https://docs.google.com/document/d/DOC_ID_1/edit\n")
    
    file_extractor = LinkExtractor(source_file_path=dummy_links_file)
    file_links = file_extractor.get_links_from_file()
    print(f"File links: {file_links}")
    os.remove(dummy_links_file)

    # Test web extraction (replace with a real page you have access to if needed)
    # This example page might not have GDrive links, it's just for structure.
    # Use a page you know has Google Drive links for better testing.
    web_extractor = LinkExtractor()
    # Example: Scrape Google itself for any "drive.google.com" links (might not find many directly)
    # google_drive_patterns = [
    #     r"drive\.google\.com/file/d/",
    #     r"docs\.google\.com/(document|spreadsheets|presentation)/d/"
    # ]
    # web_links = web_extractor.get_links_from_webpage("https://www.google.com/search?q=sample+google+drive+links", google_drive_patterns)
    # print(f"Web links: {web_links}")