import logging
from typing import Optional

from utils import get_file_id_from_url
from datastructures import DownloadTask
import config

logger = logging.getLogger(__name__)

class LinkProcessor:
    def __init__(self):
        self.export_formats_cache = {} # To ask only once per session for each type

    def _get_export_format(self, url_type: str) -> Optional[str]:
        """Prompts user for export format if not already chosen for this session."""
        if url_type in self.export_formats_cache:
            return self.export_formats_cache[url_type]

        prompt_message = ""
        default_format = ""
        valid_formats = []

        if url_type == "document":
            prompt_message = f"Enter export format for Google Doc (e.g., {', '.join(config.VALID_DOC_FORMATS)}) [default: {config.DEFAULT_DOC_FORMAT}]: "
            default_format = config.DEFAULT_DOC_FORMAT
            valid_formats = config.VALID_DOC_FORMATS
        elif url_type == "spreadsheet":
            prompt_message = f"Enter export format for Google Sheet (e.g., {', '.join(config.VALID_SHEET_FORMATS)}) [default: {config.DEFAULT_SHEET_FORMAT}]: "
            default_format = config.DEFAULT_SHEET_FORMAT
            valid_formats = config.VALID_SHEET_FORMATS
        elif url_type == "presentation":
            prompt_message = f"Enter export format for Google Slides (e.g., {', '.join(config.VALID_SLIDES_FORMATS)}) [default: {config.DEFAULT_SLIDES_FORMAT}]: "
            default_format = config.DEFAULT_SLIDES_FORMAT
            valid_formats = config.VALID_SLIDES_FORMATS
        else:
            return None # Should not happen for exportable types

        while True:
            try:
                choice = input(prompt_message).lower().strip() or default_format
                if choice in valid_formats:
                    self.export_formats_cache[url_type] = choice
                    return choice
                logger.warning(f"Invalid format '{choice}'. Please choose from: {', '.join(valid_formats)}")
            except EOFError: # Handle non-interactive environments
                logger.warning("EOFError encountered during input. Using default format.")
                self.export_formats_cache[url_type] = default_format
                return default_format


    def process_link(self, original_url: str) -> Optional[DownloadTask]:
        """
        Processes a URL to determine if and how it can be downloaded.
        Returns a DownloadTask object or None if the link is not processable.
        """
        logger.debug(f"Processing URL: {original_url}")
        file_id = get_file_id_from_url(original_url)

        if not file_id:
            logger.warning(f"Could not extract File ID from: {original_url}")
            return None

        download_url: Optional[str] = None
        filename_hint = file_id # Default hint
        file_extension = ""
        is_export = False
        export_format_chosen: Optional[str] = None

        if "/file/d/" in original_url: # Standard file link
            download_url = f"https://drive.google.com/uc?export=download&id={file_id}"
            logger.debug(f"Identified as standard GDrive file: {file_id}")
        elif "/document/d/" in original_url:
            url_type = "document"
            export_format_chosen = self._get_export_format(url_type)
            if not export_format_chosen:
                logger.warning(f"Skipping Google Doc, no export format chosen: {original_url}")
                return None
            download_url = f"https://docs.google.com/document/d/{file_id}/export?format={export_format_chosen}"
            file_extension = f".{export_format_chosen}"
            is_export = True
            logger.debug(f"Identified as GDoc: {file_id}, export format: {export_format_chosen}")
        elif "/spreadsheets/d/" in original_url:
            url_type = "spreadsheet"
            export_format_chosen = self._get_export_format(url_type)
            if not export_format_chosen:
                logger.warning(f"Skipping Google Sheet, no export format chosen: {original_url}")
                return None
            download_url = f"https://docs.google.com/spreadsheets/d/{file_id}/export?format={export_format_chosen}"
            file_extension = f".{export_format_chosen}"
            is_export = True
            logger.debug(f"Identified as GSheet: {file_id}, export format: {export_format_chosen}")
        elif "/presentation/d/" in original_url:
            url_type = "presentation"
            export_format_chosen = self._get_export_format(url_type)
            if not export_format_chosen:
                logger.warning(f"Skipping Google Slides, no export format chosen: {original_url}")
                return None
            download_url = f"https://docs.google.com/presentation/d/{file_id}/export?format={export_format_chosen}"
            file_extension = f".{export_format_chosen}"
            is_export = True
            logger.debug(f"Identified as GSlides: {file_id}, export format: {export_format_chosen}")
        elif "/drive/folders/" in original_url:
            logger.info(f"Skipping folder link (folders cannot be downloaded directly): {original_url}")
            return None
        else:
            logger.warning(f"Unrecognized Google Drive link format: {original_url}")
            return None

        if not download_url:
            logger.error(f"Could not determine download URL for: {original_url}")
            return None

        return DownloadTask(
            original_url=original_url,
            file_id=file_id,
            download_url=download_url,
            filename_hint=filename_hint, # Will be refined by downloader
            file_extension=file_extension,
            is_export=is_export,
            export_format=export_format_chosen
        )