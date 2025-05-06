from dataclasses import dataclass, field
from typing import Optional, Dict

@dataclass
class DownloadTask:
    original_url: str
    file_id: str
    download_url: str
    filename_hint: str
    file_extension: str = ""
    is_export: bool = False
    export_format: Optional[str] = None
    cookies: Dict[str, str] = field(default_factory=dict) # For session specific cookies if needed

@dataclass
class DownloadResult:
    original_url: str
    success: bool
    filepath: Optional[str] = None
    message: str = ""
    error: Optional[Exception] = None