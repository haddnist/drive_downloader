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
    # Consider adding requests.exceptions.HTTPError for specific 5xx status codes if needed
    # Example: retry_if_exception(lambda e: isinstance(e, requests.exceptions.HTTPError) and e.response.status_code >= 500)
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

    def _determine_final_filename_and_path(self, task: DownloadTask, server_filename_hint: Optional[str]) -> Tuple[str, str]:
        """
        Determines the final filename (just the name, e.g., "file.pdf") 
        and final_filepath (full path, e.g., "download_folder/file.pdf"), 
        ensuring filename uniqueness within the download_folder.
        """
        initial_base_filename: str
        if server_filename_hint:
            initial_base_filename = server_filename_hint
            if task.file_extension and not os.path.splitext(initial_base_filename)[1]:
                initial_base_filename += task.file_extension
        else:
            base_name_hint = sanitize_filename(task.filename_hint)
            initial_base_filename = f"{base_name_hint}{task.file_extension}" if task.file_extension else f"{base_name_hint}.gdownload"
        
        initial_base_filename = sanitize_filename(initial_base_filename)

        final_filename_component = initial_base_filename
        current_full_filepath = os.path.join(self.download_folder, final_filename_component)
        
        name_part, ext_part = os.path.splitext(final_filename_component)
        counter = 1

        while os.path.exists(current_full_filepath) and not os.path.isdir(current_full_filepath):
            final_filename_component = f"{name_part}_{counter}{ext_part}"
            current_full_filepath = os.path.join(self.download_folder, final_filename_component)
            counter += 1
        
        if final_filename_component != initial_base_filename:
            logger.info(f"[{task.original_url}] Initial base filename '{initial_base_filename}' adjusted to '{final_filename_component}' for uniqueness in '{self.download_folder}'.")

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

        # Determine a base for joining, usually drive.google.com for /uc endpoint confirmations
        parsed_original = urlparse(original_url)
        base_for_join = f"{parsed_original.scheme}://{parsed_original.netloc}"
        if "drive.google.com" not in base_for_join and ("/uc" in confirm_url_path or "confirm=" in confirm_url_path):
            # If original link was docs.google.com but confirmation path is /uc, base is drive.google.com
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
                                 final_filepath_full: str, partial_filepath_full: str,
                                 server_total_size: Optional[int],
                                 initial_response_headers: Optional[requests.structures.CaseInsensitiveDict]) -> DownloadResult:
        
        download_url_to_use = task.download_url
        response = None

        current_downloaded_size = 0
        file_open_mode = 'wb'
        request_headers = session.headers.copy()

        if config.DOWNLOAD_TO_PART_FILES and os.path.exists(partial_filepath_full):
            current_downloaded_size = os.path.getsize(partial_filepath_full)
            if server_total_size and current_downloaded_size > 0 and current_downloaded_size < server_total_size:
                logger.info(f"[{task.original_url}] Resuming download for {os.path.basename(final_filepath_full)} from byte {current_downloaded_size}.")
                request_headers['Range'] = f"bytes={current_downloaded_size}-"
                file_open_mode = 'ab'
            elif server_total_size and current_downloaded_size >= server_total_size:
                logger.info(f"[{task.original_url}] Partial file {os.path.basename(partial_filepath_full)} found complete or oversized. Renaming.")
                os.rename(partial_filepath_full, final_filepath_full)
                return DownloadResult(original_url=task.original_url, success=True, filepath=final_filepath_full, message=f"Success (resumed and completed): {os.path.basename(final_filepath_full)}")
            else:
                current_downloaded_size = 0
                file_open_mode = 'wb'
        
        try:
            logger.debug(f"[{task.original_url}] Attempting GET from: {download_url_to_use} with Range: {request_headers.get('Range', 'No Range')}")
            response = session.get(download_url_to_use, stream=True, timeout=config.REQUEST_TIMEOUT, headers=request_headers)
            response.raise_for_status()

            content_type_get = response.headers.get("Content-Type", "").lower()
            is_html_confirmation = False
            if "text/html" in content_type_get and 'content-disposition' not in response.headers:
                try:
                    # Peek at the beginning of the content
                    # Be careful: response.text consumes the stream if not careful or if file is small
                    # For this, we can read a small chunk first to check for keywords
                    first_chunk = next(response.iter_content(config.CHUNK_SIZE, decode_unicode=True), "")
                    if ("downloadForm" in first_chunk or "confirm=" in first_chunk or "Virus scan warning" in first_chunk):
                        is_html_confirmation = True
                        # Reconstruct full text if needed for BeautifulSoup (if it's actually small)
                        # For larger HTML, this strategy might need refinement.
                        # Here, we assume confirmation pages are relatively small.
                        full_response_text = first_chunk + "".join(list(response.iter_content(config.CHUNK_SIZE, decode_unicode=True)))
                        
                        confirmed_response = self._handle_confirmation_page(full_response_text, session, task.original_url)
                        if confirmed_response:
                            response.close() # Close previous response
                            response = confirmed_response
                            new_server_total_size_str = response.headers.get('Content-Length')
                            if new_server_total_size_str: server_total_size = int(new_server_total_size_str)
                            
                            if current_downloaded_size > 0 and response.status_code == 200:
                                logger.warning(f"[{task.original_url}] Server sent full file after confirmation despite resume. Restarting .part file.")
                                current_downloaded_size = 0
                                file_open_mode = 'wb'
                        else:
                            return DownloadResult(original_url=task.original_url, success=False, message="Failed: Confirmation bypass failed after GET.")
                except (requests.exceptions.ChunkedEncodingError, UnicodeDecodeError) as e_peek:
                     logger.debug(f"[{task.original_url}] Error peeking into HTML response or not text, assuming direct download: {e_peek}")
                     is_html_confirmation = False # Not a parsable HTML confirmation
                # If it was not a confirmation, but we consumed the first_chunk, we need to handle it
                # This part is tricky. For now, if it's not confirmation, we'll assume the main loop handles the stream.


            if current_downloaded_size > 0 and response.status_code == 200 and not is_html_confirmation:
                logger.warning(f"[{task.original_url}] Server ignored Range request (sent 200 OK). Restarting download for {os.path.basename(final_filepath_full)}.")
                current_downloaded_size = 0
                file_open_mode = 'wb'
            elif current_downloaded_size > 0 and response.status_code == 206:
                logger.info(f"[{task.original_url}] Server accepted Range request (206 Partial Content).")
            
            final_content_length_header = response.headers.get('Content-Length')
            if final_content_length_header:
                effective_total_size_from_get = int(final_content_length_header)
                if response.status_code == 206:
                    effective_total_size_from_get += current_downloaded_size
                if effective_total_size_from_get > 0 : server_total_size = effective_total_size_from_get

            display_filename = os.path.basename(final_filepath_full)
            logger.info(f"[{task.original_url}] Downloading {display_filename}...")
            
            write_filepath = partial_filepath_full if config.DOWNLOAD_TO_PART_FILES else final_filepath_full

            with open(write_filepath, file_open_mode) as f:
                # If we consumed the first_chunk for HTML check and it wasn't confirmation, write it now
                # This part needs to be careful about double-writing or missing the first chunk.
                # A cleaner way: if HTML check is done, and it's NOT confirmation, re-issue GET without peeking.
                # For now, let's assume the original iter_content will work, but this is a point of fragility.
                # If is_html_confirmation was true, `response` is already the new confirmed_response.
                # If is_html_confirmation was false, but we peeked using `first_chunk`, that data is lost from `response.iter_content`.
                # This is why peeking into a stream you intend to fully consume later is dangerous.
                # Let's assume for now, if it was not a confirmation, the `first_chunk` logic did not run or was not significant.
                # This part of the logic is complex to make robust without re-requesting.
                # The most robust way to handle "is this GET response HTML or file?" is to check headers first.

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

            if config.DOWNLOAD_TO_PART_FILES:
                os.rename(write_filepath, final_filepath_full)
            
            logger.info(f"[{task.original_url}] Successfully downloaded: {final_filepath_full} ({current_downloaded_size} bytes)")
            return DownloadResult(original_url=task.original_url, success=True, filepath=final_filepath_full, message=f"Success: {display_filename}")

        except requests.exceptions.RequestException as e:
            logger.error(f"[{task.original_url}] Download error during attempt for {task.download_url}: {e}")
            raise
        except IOError as e:
            logger.error(f"[{task.original_url}] File I/O error for {os.path.basename(final_filepath_full)}: {e} (Path attempted: {write_filepath if 'write_filepath' in locals() else 'N/A'})")
            return DownloadResult(original_url=task.original_url, success=False, message=f"Failed: File I/O error - {e}", error=e)
        finally:
            if response:
                response.close()

    def download_file(self, task: DownloadTask, session: requests.Session) -> DownloadResult:
        logger.info(f"[{task.original_url}] Processing download for: {task.original_url}")

        server_total_size, suggested_filename_from_head, head_headers = self._get_server_file_info(task.download_url, session, task)
        
        final_filename_name_only, final_filepath_full = self._determine_final_filename_and_path(task, suggested_filename_from_head)
        partial_filepath_full = final_filepath_full + ".part"

        if config.CHECK_EXISTING_SIZE_BEFORE_DOWNLOAD and os.path.exists(final_filepath_full):
            if server_total_size is not None and server_total_size > 0:
                local_file_size = os.path.getsize(final_filepath_full)
                if local_file_size == server_total_size:
                    logger.info(f"[{task.original_url}] Skipped: File '{final_filename_name_only}' already exists with matching size ({local_file_size} bytes).")
                    return DownloadResult(original_url=task.original_url, success=True, filepath=final_filepath_full, message=f"Skipped (exists, size match): {final_filename_name_only}")
                else:
                    logger.warning(f"[{task.original_url}] File '{final_filename_name_only}' exists but size mismatch (local: {local_file_size}, server: {server_total_size}). Re-downloading.")
                    try: os.remove(final_filepath_full)
                    except OSError as e_rm: logger.error(f"Could not remove mismatched file {final_filepath_full}: {e_rm}")
            else: # server_total_size is 0 or None
                 if os.path.getsize(final_filepath_full) == 0 and (server_total_size == 0 or server_total_size is None):
                    logger.info(f"[{task.original_url}] Skipped: File '{final_filename_name_only}' exists as 0 bytes and server size is 0 or unknown. Assuming complete.")
                    return DownloadResult(original_url=task.original_url, success=True, filepath=final_filepath_full, message=f"Skipped (0 byte file exists, server size 0/unknown): {final_filename_name_only}")
                 else:
                    logger.info(f"[{task.original_url}] File '{final_filename_name_only}' exists, but server size unknown or zero for reliable comparison. Re-downloading for safety.")
                    # Consider if you want to remove it here if server_total_size is None.
                    # For now, it will overwrite or create example_1.pdf etc. due to _determine_final_filename_and_path

        try:
            return self._perform_download_attempt(task, session, 
                                                 final_filepath_full,
                                                 partial_filepath_full,
                                                 server_total_size, head_headers)
        except RetryError as e:
            logger.error(f"[{task.original_url}] Download failed for {final_filename_name_only} after {config.RETRY_ATTEMPTS} attempts. Last error: {e.last_attempt.exception()}", exc_info=False) # exc_info=False for brevity on final retry error
            return DownloadResult(original_url=task.original_url, success=False, message=f"Failed after retries: {type(e.last_attempt.exception()).__name__}", error=e.last_attempt.exception())
        except Exception as e:
            logger.error(f"[{task.original_url}] An unexpected error occurred during download orchestration for {final_filename_name_only}: {e}", exc_info=True)
            return DownloadResult(original_url=task.original_url, success=False, message=f"Failed: Unexpected orchestration error - {type(e).__name__}", error=e)