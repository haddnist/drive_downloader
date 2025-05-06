# downloader.py
import os
import re
import logging
import requests
from bs4 import BeautifulSoup
from typing import Optional, Tuple
from urllib.parse import urlparse, urljoin

from tenacity import retry, stop_after_attempt, wait_exponential, RetryError, retry_if_exception_type

from datastructures import DownloadTask, DownloadResult
from utils import sanitize_filename, get_filename_from_content_disposition
import config

logger = logging.getLogger(__name__)

# Define which exceptions tenacity should retry on for downloads
RETRYABLE_EXCEPTIONS = (
    requests.exceptions.Timeout,
    requests.exceptions.ConnectionError,
    requests.exceptions.ChunkedEncodingError,
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
            head_response = session.head(url, timeout=config.REQUEST_TIMEOUT, allow_redirects=True)
            head_response.raise_for_status()
            
            content_length = int(head_response.headers.get('Content-Length', 0))
            suggested_filename_from_head = get_filename_from_content_disposition(head_response.headers)

            return content_length, suggested_filename_from_head, head_response.headers
        except requests.exceptions.RequestException as e:
            logger.warning(f"[{task.original_url}] HEAD request failed for {url}: {e}")
            return None, None, None

    def _determine_actual_final_filename_and_path(self, task: DownloadTask, initial_proposed_filename: str) -> Tuple[str, str]:
        """
        Given an initial_proposed_filename (e.g., "file.pdf"), determines the actual
        final filename component (e.g., "file.pdf" or "file_1.pdf" if "file.pdf" exists)
        and the full path. This is called *after* the skip check.
        """
        final_filename_component = initial_proposed_filename # Start with the proposed name
        current_full_filepath = os.path.join(self.download_folder, final_filename_component)
        
        name_part, ext_part = os.path.splitext(final_filename_component)
        counter = 1

        # This loop ensures the path we are about to write to is unique if the initial_proposed_filename
        # (or a version of it we intend to use) already exists for a different reason (e.g. previous failed download part)
        while os.path.exists(current_full_filepath) and not os.path.isdir(current_full_filepath):
            # This situation occurs if:
            # 1. initial_proposed_filename exists AND it was a size mismatch (so we didn't skip)
            #    AND we decided NOT to overwrite it but save as _1.
            # 2. OR initial_proposed_filename did not exist, but after some processing, the name chosen here
            #    (which should be initial_proposed_filename) coincidentally exists (e.g. a .part file from another aborted attempt).
            #    This function ensures we get a truly unique name to download TO.
            final_filename_component = f"{name_part}_{counter}{ext_part}"
            current_full_filepath = os.path.join(self.download_folder, final_filename_component)
            counter += 1
        
        if final_filename_component != initial_proposed_filename:
            logger.info(f"[{task.original_url}] Filename '{initial_proposed_filename}' will be saved as '{final_filename_component}' to ensure uniqueness or avoid conflict.")

        return final_filename_component, current_full_filepath


    def _handle_confirmation_page(self, response_text: str, session: requests.Session, original_url: str) -> Optional[requests.Response]:
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

        parsed_original = urlparse(original_url)
        base_for_join = f"{parsed_original.scheme}://{parsed_original.netloc}"
        if "drive.google.com" not in base_for_join and ("/uc" in confirm_url_path or "confirm=" in confirm_url_path):
             base_for_join = "https://drive.google.com"

        confirm_url_full = urljoin(base_for_join, confirm_url_path)
        
        logger.info(f"[{original_url}] Following confirmation URL: {confirm_url_full}")
        try:
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
            f"Download failed for {retry_state.args[0].original_url if len(retry_state.args) > 0 and hasattr(retry_state.args[0], 'original_url') else 'unknown task'} "
            f"(attempt {retry_state.attempt_number}/{config.RETRY_ATTEMPTS}). Retrying in {retry_state.next_action.sleep:.0f}s... Error: {retry_state.outcome.exception()}"
        )
    )
    def _perform_download_attempt(self, task: DownloadTask, session: requests.Session,
                                 actual_final_filepath_full: str, # The true final path (e.g., downloaded_files/file_1.pdf)
                                 actual_partial_filepath_full: str, # The true partial path (e.g., downloaded_files/file_1.pdf.part)
                                 server_total_size: Optional[int],
                                 initial_response_headers: Optional[requests.structures.CaseInsensitiveDict]) -> DownloadResult:
        
        download_url_to_use = task.download_url
        response = None

        current_downloaded_size = 0
        file_open_mode = 'wb'
        request_headers = session.headers.copy()

        if config.DOWNLOAD_TO_PART_FILES and os.path.exists(actual_partial_filepath_full):
            current_downloaded_size = os.path.getsize(actual_partial_filepath_full)
            if server_total_size and current_downloaded_size > 0 and current_downloaded_size < server_total_size:
                logger.info(f"[{task.original_url}] Resuming download for {os.path.basename(actual_final_filepath_full)} from byte {current_downloaded_size}.")
                request_headers['Range'] = f"bytes={current_downloaded_size}-"
                file_open_mode = 'ab'
            elif server_total_size and current_downloaded_size >= server_total_size:
                logger.info(f"[{task.original_url}] Partial file {os.path.basename(actual_partial_filepath_full)} found complete or oversized. Renaming.")
                os.rename(actual_partial_filepath_full, actual_final_filepath_full)
                return DownloadResult(original_url=task.original_url, success=True, filepath=actual_final_filepath_full, message=f"Success (resumed and completed): {os.path.basename(actual_final_filepath_full)}")
            else:
                current_downloaded_size = 0
                file_open_mode = 'wb'
        
        try:
            logger.debug(f"[{task.original_url}] Attempting GET from: {download_url_to_use} with Range: {request_headers.get('Range', 'No Range')}")
            response = session.get(download_url_to_use, stream=True, timeout=config.REQUEST_TIMEOUT, headers=request_headers)
            response.raise_for_status()

            content_type_get = response.headers.get("Content-Type", "").lower()
            is_html_confirmation = False # Flag to track if we handled confirmation
            
            if "text/html" in content_type_get and 'content-disposition' not in response.headers:
                # This block attempts to handle cases where the direct GET is an HTML confirmation page
                response_text_for_confirmation = ""
                try:
                    # Read the whole response if it's HTML, assuming confirmation pages are small
                    # This consumes the original response stream.
                    response_text_for_confirmation = response.text 
                except requests.exceptions.ChunkedEncodingError: # Could happen if it's a large HTML file not meant to be read all at once
                    logger.warning(f"[{task.original_url}] ChunkedEncodingError while trying to read potential HTML confirmation. Assuming not a confirmation.")
                except Exception as e_read_text: # Other errors reading text
                    logger.warning(f"[{task.original_url}] Error reading text of potential HTML confirmation: {e_read_text}. Assuming not a confirmation.")

                if response_text_for_confirmation and \
                   ("downloadForm" in response_text_for_confirmation or \
                    "confirm=" in response_text_for_confirmation or \
                    "Virus scan warning" in response_text_for_confirmation):
                    
                    is_html_confirmation = True
                    confirmed_response = self._handle_confirmation_page(response_text_for_confirmation, session, task.original_url)
                    if confirmed_response:
                        response.close() # Close the original HTML response
                        response = confirmed_response # Switch to the new response (the actual file stream)
                        new_server_total_size_str = response.headers.get('Content-Length')
                        if new_server_total_size_str: server_total_size = int(new_server_total_size_str)
                        
                        if current_downloaded_size > 0 and response.status_code == 200: # Server sent full file
                            logger.warning(f"[{task.original_url}] Server sent full file after confirmation despite resume. Restarting .part file {os.path.basename(actual_partial_filepath_full)}.")
                            current_downloaded_size = 0
                            file_open_mode = 'wb' # Overwrite .part file
                    else:
                        return DownloadResult(original_url=task.original_url, success=False, message="Failed: Confirmation bypass failed after GET.")
            
            if not is_html_confirmation: # Only check Range if we didn't just get a new stream from confirmation
                if current_downloaded_size > 0 and response.status_code == 200:
                    logger.warning(f"[{task.original_url}] Server ignored Range request (sent 200 OK). Restarting download for {os.path.basename(actual_final_filepath_full)}.")
                    current_downloaded_size = 0
                    file_open_mode = 'wb'
                elif current_downloaded_size > 0 and response.status_code == 206:
                    logger.info(f"[{task.original_url}] Server accepted Range request (206 Partial Content).")
            
            final_content_length_header = response.headers.get('Content-Length')
            if final_content_length_header:
                effective_total_size_from_get = int(final_content_length_header)
                if response.status_code == 206: # For range requests, Content-Length is remaining size
                    effective_total_size_from_get += current_downloaded_size
                if effective_total_size_from_get > 0 : server_total_size = effective_total_size_from_get

            display_filename = os.path.basename(actual_final_filepath_full)
            logger.info(f"[{task.original_url}] Downloading {display_filename} to {actual_partial_filepath_full if config.DOWNLOAD_TO_PART_FILES else actual_final_filepath_full}...")
            
            write_filepath = actual_partial_filepath_full if config.DOWNLOAD_TO_PART_FILES else actual_final_filepath_full

            with open(write_filepath, file_open_mode) as f:
                for chunk in response.iter_content(chunk_size=config.CHUNK_SIZE):
                    if chunk:
                        f.write(chunk)
                        current_downloaded_size += len(chunk)
                        if server_total_size and server_total_size > 0:
                            progress = (current_downloaded_size / server_total_size) * 100
                            if current_downloaded_size % (config.CHUNK_SIZE * 50) == 0 or current_downloaded_size == server_total_size:
                                logger.debug(f"[{task.original_url}] Downloading {display_filename}: {current_downloaded_size}/{server_total_size} bytes ({progress:.2f}%)")
            
            if server_total_size and current_downloaded_size < server_total_size:
                logger.warning(f"[{task.original_url}] Download incomplete for {display_filename}. {current_downloaded_size}/{server_total_size} bytes. Will retry if attempts left.")
                raise requests.exceptions.ConnectionError("Download stream ended prematurely.")

            if config.DOWNLOAD_TO_PART_FILES and os.path.exists(write_filepath): # Check if part file exists before renaming
                os.rename(write_filepath, actual_final_filepath_full)
            
            logger.info(f"[{task.original_url}] Successfully downloaded: {actual_final_filepath_full} ({current_downloaded_size} bytes)")
            return DownloadResult(original_url=task.original_url, success=True, filepath=actual_final_filepath_full, message=f"Success: {display_filename}")

        except requests.exceptions.RequestException as e:
            logger.error(f"[{task.original_url}] Download error during attempt for {task.download_url}: {e}")
            raise
        except IOError as e:
            logger.error(f"[{task.original_url}] File I/O error for {os.path.basename(actual_final_filepath_full)}: {e} (Path attempted: {write_filepath if 'write_filepath' in locals() else 'N/A'})")
            return DownloadResult(original_url=task.original_url, success=False, message=f"Failed: File I/O error - {e}", error=e)
        finally:
            if response:
                response.close()

    def download_file(self, task: DownloadTask, session: requests.Session) -> DownloadResult:
        logger.info(f"[{task.original_url}] Processing download for: {task.original_url}")

        server_total_size, suggested_filename_from_head, head_headers = self._get_server_file_info(task.download_url, session, task)
        
        # --- Step 1: Determine the INITIAL proposed filename (just the name part) ---
        initial_proposed_filename_name_only: str
        if suggested_filename_from_head:
            initial_proposed_filename_name_only = suggested_filename_from_head
            if task.file_extension and not os.path.splitext(initial_proposed_filename_name_only)[1]:
                initial_proposed_filename_name_only += task.file_extension
        else:
            base_name_hint = sanitize_filename(task.filename_hint)
            initial_proposed_filename_name_only = f"{base_name_hint}{task.file_extension}" if task.file_extension else f"{base_name_hint}.gdownload"
        initial_proposed_filename_name_only = sanitize_filename(initial_proposed_filename_name_only)
        
        # --- Step 2: Construct the full path for this initial proposed filename ---
        initial_proposed_filepath_full = os.path.join(self.download_folder, initial_proposed_filename_name_only)

        # --- Step 3: Check if this INITIAL proposed file already exists and should be skipped ---
        if config.CHECK_EXISTING_SIZE_BEFORE_DOWNLOAD and os.path.exists(initial_proposed_filepath_full):
            if server_total_size is not None and server_total_size > 0: # We have a server size to compare against
                local_file_size = os.path.getsize(initial_proposed_filepath_full)
                if local_file_size == server_total_size:
                    logger.info(f"[{task.original_url}] Skipped: File '{initial_proposed_filename_name_only}' already exists with matching size ({local_file_size} bytes).")
                    return DownloadResult(original_url=task.original_url, success=True, filepath=initial_proposed_filepath_full, message=f"Skipped (exists, size match): {initial_proposed_filename_name_only}")
                else:
                    logger.warning(f"[{task.original_url}] File '{initial_proposed_filename_name_only}' exists but size mismatch (local: {local_file_size}, server: {server_total_size}). Will proceed to download, possibly overwriting or creating a new version (e.g., _1).")
                    # If we reach here, we will effectively overwrite `initial_proposed_filepath_full` if no other file forces a `_1` suffix,
                    # or a `_1` suffix will be created by _determine_actual_final_filename_and_path.
            elif os.path.getsize(initial_proposed_filepath_full) == 0 and (server_total_size == 0 or server_total_size is None):
                 logger.info(f"[{task.original_url}] Skipped: File '{initial_proposed_filename_name_only}' exists as 0 bytes and server size is 0 or unknown. Assuming complete.")
                 return DownloadResult(original_url=task.original_url, success=True, filepath=initial_proposed_filepath_full, message=f"Skipped (0 byte file exists, server size 0/unknown): {initial_proposed_filename_name_only}")
            else: # File exists, but server size is None or not > 0. Cannot reliably compare.
                 logger.info(f"[{task.original_url}] File '{initial_proposed_filename_name_only}' exists, but server size unavailable for comparison. Will proceed to download, possibly creating a new version (e.g., _1).")

        # --- Step 4: If not skipped, determine the ACTUAL final (potentially unique) filename and path ---
        # This function is now simpler: it takes the initial_proposed_filename_name_only and makes it unique if that *exact name* is taken.
        actual_final_filename_name_only, actual_final_filepath_full = self._determine_actual_final_filename_and_path(task, initial_proposed_filename_name_only)
        actual_partial_filepath_full = actual_final_filepath_full + ".part"
        
        # --- Step 5: Handle overwrite of a mismatched initial file if the actual final name is the same ---
        # This ensures that if "file.pdf" exists and is bad, and we decide to download "file.pdf" again (not "file_1.pdf"),
        # we remove the bad "file.pdf" first.
        if actual_final_filepath_full == initial_proposed_filepath_full and \
           os.path.exists(initial_proposed_filepath_full) and \
           config.CHECK_EXISTING_SIZE_BEFORE_DOWNLOAD and \
           server_total_size is not None and \
           ( (server_total_size > 0 and os.path.getsize(initial_proposed_filepath_full) != server_total_size) or \
             (server_total_size == 0 and os.path.getsize(initial_proposed_filepath_full) != 0) ): # Mismatch also if server is 0 and local isn't
            logger.warning(f"[{task.original_url}] Explicitly removing mismatched file before overwrite: {initial_proposed_filepath_full}")
            try:
                if os.path.exists(actual_partial_filepath_full): # remove its .part file too if it exists
                    os.remove(actual_partial_filepath_full)
                os.remove(initial_proposed_filepath_full)
            except OSError as e_rm:
                logger.error(f"Could not remove mismatched file {initial_proposed_filepath_full} for overwrite: {e_rm}. Download may fail or save with suffix.")


        # --- Step 6: Execute download with retries ---
        try:
            return self._perform_download_attempt(task, session, 
                                                 actual_final_filepath_full,
                                                 actual_partial_filepath_full,
                                                 server_total_size, head_headers)
        except RetryError as e:
            logger.error(f"[{task.original_url}] Download failed for {actual_final_filename_name_only} after {config.RETRY_ATTEMPTS} attempts. Last error: {e.last_attempt.exception()}", exc_info=False)
            return DownloadResult(original_url=task.original_url, success=False, message=f"Failed after retries: {type(e.last_attempt.exception()).__name__}", error=e.last_attempt.exception())
        except Exception as e:
            logger.error(f"[{task.original_url}] An unexpected error occurred during download orchestration for {actual_final_filename_name_only}: {e}", exc_info=True)
            return DownloadResult(original_url=task.original_url, success=False, message=f"Failed: Unexpected orchestration error - {type(e).__name__}", error=e)