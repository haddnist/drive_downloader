# downloader.py
import os
import re
import logging
import requests
from bs4 import BeautifulSoup # For handling confirmation pages
from typing import Optional # <<< ADD THIS IMPORT

from datastructures import DownloadTask, DownloadResult
from utils import sanitize_filename, get_filename_from_content_disposition
import config

logger = logging.getLogger(__name__)

class Downloader:
    def __init__(self, download_folder: str):
        self.download_folder = download_folder
        os.makedirs(self.download_folder, exist_ok=True)

    # The error pointed to this type hint
    def _handle_confirmation_page(self, response_text: str, session: requests.Session, original_url: str) -> Optional[requests.Response]:
        """Attempts to bypass Google Drive's 'large file' confirmation page."""
        logger.info(f"Confirmation page detected for {original_url}. Attempting to bypass...")
        soup = BeautifulSoup(response_text, 'html.parser')
        confirm_url = None

        # Try to find a form action URL
        form = soup.find('form', {'id': 'downloadForm'})
        if form and form.get('action'):
            confirm_url = form.get('action')
        else: # Try to find a direct confirmation link
            confirm_link_tag = soup.find('a', href=re.compile(r'confirm='))
            if confirm_link_tag and confirm_link_tag.get('href'):
                confirm_url = confirm_link_tag.get('href')

        if not confirm_url:
            logger.error(f"Could not find confirmation link/form on page for {original_url}")
            return None

        # Ensure it's a full URL
        if not confirm_url.startswith('http'):
            # Determine base URL more intelligently if needed, but drive.google.com is common for confirmation
            # Check if original_url or task.download_url gives a better hint for docs.google.com etc.
            # For now, drive.google.com is a reasonable default for the uc download controller.
            base_drive_url = "https://drive.google.com"
            confirm_url = f"{base_drive_url}{confirm_url}" if confirm_url.startswith('/') else f"{base_drive_url}/uc{confirm_url}"
        
        logger.info(f"Following confirmation URL: {confirm_url}")
        try:
            # Accessing response.cookies here was problematic, pass session cookies instead.
            # The session object itself will handle cookies appropriately.
            confirmed_response = session.get(
                confirm_url,
                stream=True,
                timeout=config.DOWNLOAD_TIMEOUT
                # cookies=response.cookies # This was problematic, session handles cookies
            )
            confirmed_response.raise_for_status()
            return confirmed_response
        except requests.exceptions.RequestException as e:
            logger.error(f"Error following confirmation for {original_url}: {e}")
            return None


    def download_file(self, task: DownloadTask, session: requests.Session) -> DownloadResult:
        logger.info(f"Starting download for: {task.original_url}")
        final_filename = ""
        response_for_cookies = None # To hold the response object if we need its cookies for confirmation
        try:
            # Initial request
            response = session.get(task.download_url, stream=True, timeout=config.REQUEST_TIMEOUT)
            response_for_cookies = response # Store the response
            response.raise_for_status()

            # Check for confirmation page
            content_type = response.headers.get("Content-Type", "").lower()
            is_html_response = "text/html" in content_type
            
            # Heuristic for confirmation: HTML page that isn't an error, and contains download keywords
            # Read response.text only if it's likely HTML to avoid issues with large binary files
            response_text_for_confirmation = ""
            if is_html_response:
                try:
                    # Peek at the beginning of the content without consuming the stream for download
                    # This is tricky with streaming. Better to re-fetch if it's a confirmation page,
                    # or read a small chunk. For now, let's assume if it's HTML and small, it could be confirmation.
                    # A more robust way is to check if content-disposition is NOT set.
                    if 'content-disposition' not in response.headers:
                         # Try to decode a small part. If it fails, it's likely not text.
                        peek_content = next(response.iter_content(chunk_size=2048, decode_unicode=True), "")
                        if "downloadForm" in peek_content or "confirm=" in peek_content or "Virus scan warning" in peek_content:
                            # Since we consumed a bit, if it IS a confirmation, we need the full text.
                            # It's often better to make the confirmation handler re-fetch or have the initial response not streamed
                            # if it's small and HTML. However, for simplicity, let's get the full text if it looks like HTML.
                            # This means if a *downloadable* file IS HTML and small, it'll be read into memory here.
                            if response.content: # If not already consumed by iter_content
                                response_text_for_confirmation = response.text
                            else: # if iter_content was already used, this response object is partially consumed
                                # This branch is less likely if we are careful above
                                # Re-fetch the URL without streaming to get the HTML content for parsing
                                temp_resp = session.get(task.download_url, timeout=config.REQUEST_TIMEOUT)
                                response_text_for_confirmation = temp_resp.text


                except UnicodeDecodeError:
                    logger.debug("Content is HTML but cannot be decoded as text, likely a binary download misidentified.")
                    is_html_response = False # Treat as not HTML for confirmation check
                except Exception as e:
                    logger.debug(f"Error peeking into HTML response content: {e}")
                    # Could be a very large HTML page, proceed carefully
            
            if is_html_response and response_text_for_confirmation and \
               ("downloadForm" in response_text_for_confirmation or \
                "confirm=" in response_text_for_confirmation or \
                "Virus scan warning" in response_text_for_confirmation):
                # Pass the original response object (response_for_cookies) so its cookies can be used by the session
                # if the session itself didn't pick them up for the confirmation redirect.
                # However, the session object *should* handle cookies correctly across redirects
                # if the server sets them properly.
                confirmed_response = self._handle_confirmation_page(response_text_for_confirmation, session, task.original_url)
                if confirmed_response:
                    response = confirmed_response 
                else:
                    return DownloadResult(original_url=task.original_url, success=False, message="Failed: Confirmation bypass failed.")

            # Determine filename
            filename_from_header = get_filename_from_content_disposition(response.headers)
            
            if filename_from_header:
                final_filename = filename_from_header
                if task.file_extension and not os.path.splitext(final_filename)[1]:
                    final_filename += task.file_extension
            else:
                base_name = sanitize_filename(task.filename_hint)
                final_filename = f"{base_name}{task.file_extension}" if task.file_extension else f"{base_name}.gdownload"
            
            final_filename = sanitize_filename(final_filename)
            filepath = os.path.join(self.download_folder, final_filename)

            logger.info(f"Resolved filename: {final_filename}. Saving to: {filepath}")
            
            total_size = int(response.headers.get('content-length', 0))
            downloaded_size = 0
            
            counter = 1
            base, ext = os.path.splitext(filepath)
            while os.path.exists(filepath):
                filepath = f"{base}_{counter}{ext}"
                final_filename = os.path.basename(filepath)
                counter +=1
            if counter > 1:
                logger.info(f"File existed, new name: {final_filename}")

            with open(filepath, 'wb') as f:
                for chunk in response.iter_content(chunk_size=config.CHUNK_SIZE):
                    if chunk:
                        f.write(chunk)
                        downloaded_size += len(chunk)
                        if total_size > 0:
                            progress = (downloaded_size / total_size) * 100
                            if downloaded_size % (config.CHUNK_SIZE * 100) == 0 :
                                logger.debug(f"Downloading {final_filename}: {downloaded_size}/{total_size} bytes ({progress:.2f}%)")
            
            if total_size == 0 and downloaded_size == 0 and not task.is_export:
                 if "text/html" in response.headers.get("Content-Type", "").lower():
                    logger.warning(f"Downloaded 0 bytes and content type is HTML for {final_filename}. Possible error page or access issue.")
                    # os.remove(filepath) # Decide if you want to auto-delete
                    # return DownloadResult(original_url=task.original_url, success=False, message=f"Failed: Downloaded 0 bytes (HTML content) for {final_filename}", filepath=filepath)

            logger.info(f"Successfully downloaded: {filepath} ({downloaded_size} bytes)")
            return DownloadResult(original_url=task.original_url, success=True, filepath=filepath, message=f"Success: {final_filename}")

        except requests.exceptions.HTTPError as e:
            err_resp = e.response
            logger.error(f"HTTP error for {task.original_url} (URL: {err_resp.url if err_resp else task.download_url}, Status: {err_resp.status_code if err_resp else 'N/A'}): {e}")
            return DownloadResult(original_url=task.original_url, success=False, message=f"Failed: HTTP Error {err_resp.status_code if err_resp else 'Unknown'}", error=e)
        except requests.exceptions.ConnectionError as e:
            logger.error(f"Connection error for {task.original_url}: {e}")
            return DownloadResult(original_url=task.original_url, success=False, message="Failed: Connection error", error=e)
        except requests.exceptions.Timeout as e:
            logger.error(f"Timeout error for {task.original_url}: {e}")
            return DownloadResult(original_url=task.original_url, success=False, message="Failed: Timeout", error=e)
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error for {task.original_url}: {e}")
            return DownloadResult(original_url=task.original_url, success=False, message=f"Failed: {type(e).__name__}", error=e)
        except IOError as e:
            logger.error(f"File I/O error for {final_filename if final_filename else task.original_url}: {e}")
            return DownloadResult(original_url=task.original_url, success=False, message="Failed: File I/O error", error=e)
        except Exception as e:
            logger.error(f"An unexpected error occurred for {task.original_url}: {e}", exc_info=True)
            return DownloadResult(original_url=task.original_url, success=False, message=f"Failed: Unexpected error - {type(e).__name__}", error=e)
        finally:
            # Ensure the response content is consumed and the connection is released,
            # especially if an error occurred mid-stream or if it wasn't fully read.
            if 'response' in locals() and response:
                try:
                    response.close() # Releases the connection back to the pool.
                except Exception as e_close:
                    logger.debug(f"Error closing response for {task.original_url}: {e_close}")