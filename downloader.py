# downloader.py
import os
import re
import logging
import time # For manual delays if needed, though tenacity handles it
import requests
from bs4 import BeautifulSoup
from typing import Optional, Tuple, Dict

from tenacity import retry, stop_after_attempt, wait_exponential, RetryError, retry_if_exception_type

from datastructures import DownloadTask, DownloadResult
from utils import sanitize_filename, get_filename_from_content_disposition
import config

logger = logging.getLogger(__name__)

# Define which exceptions tenacity should retry on for downloads
RETRYABLE_EXCEPTIONS = (
    requests.exceptions.Timeout,
    requests.exceptions.ConnectionError,
    requests.exceptions.ChunkedEncodingError, # Can happen with unstable connections
    # Add requests.exceptions.HTTPError here if you want to retry on 5xx server errors
    # but be cautious as some HTTP errors are permanent (e.g. 404)
)

class Downloader:
    def __init__(self, download_folder: str):
        self.download_folder = download_folder
        os.makedirs(self.download_folder, exist_ok=True)

    def _get_server_file_info(self, url: str, session: requests.Session, task: DownloadTask) -> Tuple[Optional[int], Optional[str], Optional[requests.structures.CaseInsensitiveDict]]:
        """
        Performs a HEAD request to get file size and suggested filename.
        Returns: (content_length, suggested_filename, headers)
        """
        try:
            logger.debug(f"[{task.original_url}] Sending HEAD request to: {url}")
            head_response = session.head(url, timeout=config.REQUEST_TIMEOUT, allow_redirects=True) # Allow redirects for HEAD
            head_response.raise_for_status()
            
            content_length = int(head_response.headers.get('Content-Length', 0))
            
            # Try to get filename from Content-Disposition of HEAD request
            # This is useful if the direct download URL is different and has its own CD header
            suggested_filename_from_head = get_filename_from_content_disposition(head_response.headers)

            return content_length, suggested_filename_from_head, head_response.headers
        except requests.exceptions.RequestException as e:
            logger.warning(f"[{task.original_url}] HEAD request failed for {url}: {e}")
            return None, None, None

    def _determine_final_filename_and_path(self, task: DownloadTask, server_filename_hint: Optional[str]) -> Tuple[str, str]:
        """Determines the final filename and path, ensuring uniqueness."""
        if server_filename_hint:
            base_filename = server_filename_hint
            # If header filename has no extension, but we expect one (from export)
            if task.file_extension and not os.path.splitext(base_filename)[1]:
                base_filename += task.file_extension
        else:
            base_name_hint = sanitize_filename(task.filename_hint)
            base_filename = f"{base_name_hint}{task.file_extension}" if task.file_extension else f"{base_name_hint}.gdownload"
        
        base_filename = sanitize_filename(base_filename)

        # Ensure unique filename if final file (not .part) exists
        # This uniqueness check should be for the *final* file name, not the .part file.
        final_filepath_candidate = os.path.join(self.download_folder, base_filename)
        counter = 1
        actual_base, actual_ext = os.path.splitext(final_filepath_candidate)
        
        # This loop is for making the *target* filename unique if base_filename already exists.
        # It does NOT check for .part files yet.
        final_filename_to_use = base_filename
        current_final_filepath = final_filepath_candidate
        while os.path.exists(current_final_filepath) and not os.path.isdir(current_final_filepath):
            # If we are NOT checking existing sizes, we must ensure a unique name from the start.
            # If we ARE checking existing sizes, this loop might be redundant if the existing file is identical
            # and we decide to skip it. However, it's safer to assume we might need a unique name.
            final_filename_to_use = f"{actual_base}_{counter}{actual_ext}"
            current_final_filepath = os.path.join(self.download_folder, final_filename_to_use)
            counter += 1
        
        if final_filename_to_use != base_filename:
            logger.info(f"[{task.original_url}] Base filename '{base_filename}' adjusted to '{final_filename_to_use}' due to existing file(s).")

        return final_filename_to_use, os.path.join(self.download_folder, final_filename_to_use)


    def _handle_confirmation_page(self, response_text: str, session: requests.Session, original_url: str, task: DownloadTask) -> Optional[requests.Response]:
        logger.info(f"[{original_url}] Confirmation page detected. Attempting to bypass...")
        soup = BeautifulSoup(response_text, 'html.parser')
        confirm_url_path = None

        form = soup.find('form', {'id': 'downloadForm'})
        if form and form.get('action'):
            confirm_url_path = form.get('action')
        else:
            confirm_link_tag = soup.find('a', href=re.compile(r'confirm='))
            if confirm_link_tag and confirm_link_tag.get('href'):
                confirm_url_path = confirm_link_tag.get('href')

        if not confirm_url_path:
            logger.error(f"[{original_url}] Could not find confirmation link/form on page.")
            return None

        # Construct full confirmation URL
        # The confirmation URL is usually relative to drive.google.com
        # task.download_url might be docs.google.com, so use a fixed base or derive from original_url
        from urllib.parse import urlparse, urljoin
        parsed_original_url = urlparse(original_url)
        base_url_for_confirmation = f"{parsed_original_url.scheme}://{parsed_original_url.netloc}"
        
        # A common base for uc controller if path is relative
        if not confirm_url_path.startswith('http') and not confirm_url_path.startswith('/'):
             base_url_for_confirmation = "https://drive.google.com/uc"


        confirm_url_full = urljoin(base_url_for_confirmation, confirm_url_path)
        
        logger.info(f"[{original_url}] Following confirmation URL: {confirm_url_full}")
        try:
            # For the GET request that follows confirmation, we might need info from HEAD again
            # Or, we can just stream this GET. Let's assume this GET is the actual download stream.
            confirmed_response = session.get(
                confirm_url_full,
                stream=True,
                timeout=config.DOWNLOAD_TIMEOUT
            )
            confirmed_response.raise_for_status()
            return confirmed_response
        except requests.exceptions.RequestException as e:
            logger.error(f"[{original_url}] Error following confirmation: {e}")
            return None

    @retry(
        stop=stop_after_attempt(config.RETRY_ATTEMPTS),
        wait=wait_exponential(multiplier=config.RETRY_WAIT_SECONDS, max=config.RETRY_MAX_WAIT_SECONDS),
        retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
        before_sleep=lambda retry_state: logger.warning(
            f"Download failed for {retry_state.args[0].original_url if retry_state.args else 'unknown task'} "
            f"(attempt {retry_state.attempt_number}/{config.RETRY_ATTEMPTS}). Retrying in {retry_state.next_action.sleep:.0f}s... Error: {retry_state.outcome.exception()}"
        )
    )
    def _perform_download_attempt(self, task: DownloadTask, session: requests.Session,
                                 final_filepath: str, partial_filepath: str,
                                 server_total_size: Optional[int],
                                 initial_response_headers: Optional[requests.structures.CaseInsensitiveDict]) -> DownloadResult:
        
        download_url_to_use = task.download_url # Default
        response = None # Initialize response

        # --- Stage 1: Initial GET request preparation (handling resume) ---
        current_downloaded_size = 0
        file_open_mode = 'wb'
        request_headers = session.headers.copy() # Start with session headers

        if config.DOWNLOAD_TO_PART_FILES and os.path.exists(partial_filepath):
            current_downloaded_size = os.path.getsize(partial_filepath)
            if server_total_size and current_downloaded_size > 0 and current_downloaded_size < server_total_size:
                logger.info(f"[{task.original_url}] Resuming download for {os.path.basename(final_filepath)} from byte {current_downloaded_size}.")
                request_headers['Range'] = f"bytes={current_downloaded_size}-"
                file_open_mode = 'ab'
            elif server_total_size and current_downloaded_size >= server_total_size:
                logger.info(f"[{task.original_url}] Partial file {os.path.basename(partial_filepath)} found complete or oversized. Renaming.")
                os.rename(partial_filepath, final_filepath)
                return DownloadResult(original_url=task.original_url, success=True, filepath=final_filepath, message=f"Success (resumed and completed): {os.path.basename(final_filepath)}")
            else: # Partial file is 0 bytes or server_total_size unknown, start fresh
                current_downloaded_size = 0
                file_open_mode = 'wb'
        
        try:
            logger.debug(f"[{task.original_url}] Attempting GET from: {download_url_to_use} with headers: {request_headers.get('Range', 'No Range')}")
            response = session.get(download_url_to_use, stream=True, timeout=config.REQUEST_TIMEOUT, headers=request_headers)
            response.raise_for_status()

            # --- Stage 2: Handle potential confirmation page on GET response ---
            content_type_get = response.headers.get("Content-Type", "").lower()
            # Check if this GET response is an HTML confirmation page
            # A more robust check might involve looking for specific form elements or lack of Content-Disposition
            if "text/html" in content_type_get and 'content-disposition' not in response.headers:
                # Peek into content to confirm. Consuming response.text here is okay if it's small HTML.
                response_text_peek = response.text # This consumes the stream if it's small.
                if ("downloadForm" in response_text_peek or "confirm=" in response_text_peek or "Virus scan warning" in response_text_peek):
                    confirmed_response = self._handle_confirmation_page(response_text_peek, session, task.original_url, task)
                    if confirmed_response:
                        response = confirmed_response # Use the new response for download
                        # Server total size might change after confirmation, re-evaluate if important
                        new_server_total_size = int(response.headers.get('Content-Length', 0))
                        if new_server_total_size > 0: server_total_size = new_server_total_size
                        
                        # If we were resuming, but confirmation reset the stream, we need to restart writing the .part file
                        if current_downloaded_size > 0 and response.status_code == 200: # Server sent full file
                            logger.warning(f"[{task.original_url}] Server sent full file after confirmation despite resume attempt. Restarting .part file.")
                            current_downloaded_size = 0
                            file_open_mode = 'wb'
                    else:
                        return DownloadResult(original_url=task.original_url, success=False, message="Failed: Confirmation bypass failed after GET.")
            
            # --- Stage 3: Process actual download stream ---
            # Handle if server ignored Range request and sent 200 OK instead of 206 Partial Content
            if current_downloaded_size > 0 and response.status_code == 200:
                logger.warning(f"[{task.original_url}] Server ignored Range request (sent 200 OK). Restarting download for {os.path.basename(final_filepath)}.")
                current_downloaded_size = 0
                file_open_mode = 'wb'
            elif current_downloaded_size > 0 and response.status_code == 206:
                logger.info(f"[{task.original_url}] Server accepted Range request (206 Partial Content).")
            
            # Use Content-Length from this final response if available, could be more accurate than HEAD
            final_content_length_header = response.headers.get('Content-Length')
            if final_content_length_header:
                effective_total_size = int(final_content_length_header)
                if response.status_code == 206: # For range requests, Content-Length is remaining size
                    effective_total_size += current_downloaded_size
                if effective_total_size > 0 : server_total_size = effective_total_size


            display_filename = os.path.basename(final_filepath)
            logger.info(f"[{task.original_url}] Downloading {display_filename}...")
            
            # Choose the correct file path to write to
            write_filepath = partial_filepath if config.DOWNLOAD_TO_PART_FILES else final_filepath

            with open(write_filepath, file_open_mode) as f:
                for chunk in response.iter_content(chunk_size=config.CHUNK_SIZE):
                    if chunk:
                        f.write(chunk)
                        current_downloaded_size += len(chunk)
                        if server_total_size and server_total_size > 0:
                            progress = (current_downloaded_size / server_total_size) * 100
                            # Reduce log verbosity for progress
                            if current_downloaded_size % (config.CHUNK_SIZE * 50) == 0 or current_downloaded_size == server_total_size:
                                logger.debug(f"[{task.original_url}] Downloading {display_filename}: {current_downloaded_size}/{server_total_size} bytes ({progress:.2f}%)")
            
            # --- Stage 4: Finalize download ---
            if server_total_size and current_downloaded_size < server_total_size:
                # This means the download was interrupted before tenacity gave up or network issue
                logger.warning(f"[{task.original_url}] Download incomplete for {display_filename}. {current_downloaded_size}/{server_total_size} bytes. Will retry if attempts left.")
                # Raise an exception that tenacity can catch to trigger a retry
                raise requests.exceptions.ConnectionError("Download stream ended prematurely.")


            if config.DOWNLOAD_TO_PART_FILES:
                os.rename(write_filepath, final_filepath)
            
            logger.info(f"[{task.original_url}] Successfully downloaded: {final_filepath} ({current_downloaded_size} bytes)")
            return DownloadResult(original_url=task.original_url, success=True, filepath=final_filepath, message=f"Success: {display_filename}")

        except requests.exceptions.RequestException as e: # This will be caught by tenacity for retries if applicable
            logger.error(f"[{task.original_url}] Download error for {task.download_url}: {e}")
            # Let tenacity handle retry by re-raising
            raise
        except IOError as e:
            logger.error(f"[{task.original_url}] File I/O error for {os.path.basename(final_filepath)}: {e}")
            # IOErrors are not typically retried by this setup
            return DownloadResult(original_url=task.original_url, success=False, message="Failed: File I/O error", error=e)
        finally:
            if response:
                response.close()


    def download_file(self, task: DownloadTask, session: requests.Session) -> DownloadResult:
        logger.info(f"[{task.original_url}] Processing download for: {task.original_url}")

        # --- Step 1: Get server file info (size, suggested name) using HEAD ---
        server_total_size, suggested_filename_from_head, _ = self._get_server_file_info(task.download_url, session, task)
        
        # If HEAD fails, we might still try GET, but size check and resume might be unreliable
        if server_total_size is None: # Indicates HEAD request failed significantly
            logger.warning(f"[{task.original_url}] HEAD request failed. Proceeding with GET, but size checks and resume might be impaired.")
            # We can try to get filename from initial response of GET later, or use task hints.

        # --- Step 2: Determine final filename and paths ---
        # Use filename from HEAD if available, otherwise fall back to task hints
        final_filename, final_filepath = self._determine_final_filename_and_path(task, suggested_filename_from_head)
        partial_filepath = final_filepath + ".part"

        # --- Step 3: Check for existing complete file (if enabled) ---
        if config.CHECK_EXISTING_SIZE_BEFORE_DOWNLOAD and os.path.exists(final_filepath):
            if server_total_size is not None and server_total_size > 0: # Only if we have a server size
                local_file_size = os.path.getsize(final_filepath)
                if local_file_size == server_total_size:
                    logger.info(f"[{task.original_url}] Skipped: File '{final_filename}' already exists with matching size ({local_file_size} bytes).")
                    return DownloadResult(original_url=task.original_url, success=True, filepath=final_filepath, message=f"Skipped (exists, size match): {final_filename}")
                else:
                    logger.warning(f"[{task.original_url}] File '{final_filename}' exists but size mismatch (local: {local_file_size}, server: {server_total_size}). Re-downloading.")
                    try: os.remove(final_filepath) # Remove mismatched file
                    except OSError as e_rm: logger.error(f"Could not remove mismatched file {final_filepath}: {e_rm}")
            else:
                logger.info(f"[{task.original_url}] File '{final_filename}' exists, but server size unknown or zero. Cannot verify. Re-downloading for safety or use task hints.")
                # Optionally, could decide to skip if server_total_size is 0 and local is 0.

        # --- Step 4: Execute download with retries ---
        try:
            return self._perform_download_attempt(task, session, final_filepath, partial_filepath, server_total_size, None)
        except RetryError as e: # When tenacity gives up
            logger.error(f"[{task.original_url}] Download failed for {final_filename} after {config.RETRY_ATTEMPTS} attempts. Last error: {e.last_attempt.exception()}")
            return DownloadResult(original_url=task.original_url, success=False, message=f"Failed after retries: {e.last_attempt.exception()}", error=e.last_attempt.exception())
        except Exception as e: # Catch any other unexpected errors from _perform_download_attempt if not RequestException
            logger.error(f"[{task.original_url}] An unexpected error occurred during download preparation for {final_filename}: {e}", exc_info=True)
            return DownloadResult(original_url=task.original_url, success=False, message=f"Failed: Unexpected error - {type(e).__name__}", error=e)