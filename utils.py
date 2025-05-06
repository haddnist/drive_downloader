import re
import os
from urllib.parse import unquote
import logging

logger = logging.getLogger(__name__)

def sanitize_filename(filename):
    """Removes invalid characters from a filename and limits length."""
    if not filename:
        return "unnamed_file"
    # Remove path components
    filename = os.path.basename(filename)
    # Remove invalid characters
    filename = re.sub(r'[\\/*?:"<>|]', "", filename)
    # Replace multiple spaces/underscores with a single one
    filename = re.sub(r'[\s_]+', '_', filename).strip('_')
    # Limit length (common filesystem limit is 255, leave room for extensions)
    max_len = 240
    if len(filename) > max_len:
        name, ext = os.path.splitext(filename)
        filename = name[:max_len - len(ext)] + ext
        logger.debug(f"Sanitized and truncated filename to: {filename}")
    return filename if filename else "unnamed_file"

def get_file_id_from_url(url):
    """Extracts the file ID from various Google Drive URL formats."""
    patterns = [
        r"/file/d/([a-zA-Z0-9_-]+)",
        r"/document/d/([a-zA-Z0-9_-]+)",
        r"/spreadsheets/d/([a-zA-Z0-9_-]+)",
        r"/presentation/d/([a-zA-Z0-9_-]+)",
        r"id=([a-zA-Z0-9_-]+)" # For some direct links
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    logger.debug(f"Could not extract File ID from: {url}")
    return None

def get_filename_from_content_disposition(headers):
    """Extracts filename from Content-Disposition header."""
    cd = headers.get("Content-Disposition")
    if not cd:
        return None
    
    # Try to find filename*=UTF-8''...
    fname_match = re.search(r"filename\*=UTF-8''([^;]+)", cd, flags=re.IGNORECASE)
    if fname_match:
        try:
            filename = unquote(fname_match.group(1), encoding='utf-8')
            return sanitize_filename(filename)
        except Exception as e:
            logger.warning(f"Could not decode UTF-8 filename from Content-Disposition: {fname_match.group(1)}, error: {e}")

    # Fallback to filename="..."
    fname_match = re.search(r'filename="?([^"]+)"?', cd, flags=re.IGNORECASE)
    if fname_match:
        # This might not be URL encoded, but sometimes it is partially.
        # unquote can handle non-encoded strings gracefully.
        filename = unquote(fname_match.group(1))
        return sanitize_filename(filename)
        
    logger.debug(f"Could not parse filename from Content-Disposition: {cd}")
    return None