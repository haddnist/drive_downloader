# Google Drive/Docs Downloader

## Table of Contents

1.  [Overview](#overview)
2.  [Features](#features)
3.  [Prerequisites](#prerequisites)
4.  [Installation](#installation)
5.  [Directory Structure](#directory-structure)
6.  [Usage (Command Line)](#usage-command-line)
    *   [Scraping a Webpage](#scraping-a-webpage)
    *   [Using a Local Links File](#using-a-local-links-file)
    *   [Default Behavior (Using `config.py`)](#default-behavior-using-configpy)
    *   [Getting Help](#getting-help)
7.  [Configuration (`config.py`)](#configuration-configpy)
    *   [Core Settings](#core-settings)
    *   [Web Scraping Settings](#web-scraping-settings)
    *   [Google Drive Export Settings](#google-drive-export-settings)
    *   [Logging Configuration](#logging-configuration)
    *   [Request Settings](#request-settings)
8.  [How It Works (Workflow)](#how-it-works-workflow)
9.  [Detailed Component Breakdown](#detailed-component-breakdown)
    *   [`main.py`](#mainpy)
    *   [`config.py`](#configpy-details)
    *   [`link_extractor.py` (Class: `LinkExtractor`)](#link_extractorpy-class-linkextractor)
    *   [`link_processor.py` (Class: `LinkProcessor`)](#link_processorpy-class-linkprocessor)
    *   [`downloader.py` (Class: `Downloader`)](#downloaderpy-class-downloader)
    *   [`utils.py`](#utilspy)
    *   [`datastructures.py`](#datastructurespy)
10. [Error Handling and Logging](#error-handling-and-logging)
11. [Troubleshooting Common Issues](#troubleshooting-common-issues)
12. [Future Enhancements](#future-enhancements)

---
## 1. Overview

The Google Drive/Docs Downloader is a Python program designed to download files from Google Drive. It can accept a list of Google Drive or Google Docs/Sheets/Slides URLs from a local file or scrape them from a specified webpage. For Google Docs, Sheets, and Slides, it allows exporting to various formats (e.g., PDF, DOCX, XLSX, PPTX). The program utilizes concurrency to download multiple files efficiently.

---
## 2. Features

*   **Modular Design:** Code is organized into separate modules for clarity and maintainability.
*   **Flexible Link Sourcing:**
    *   Scrape Google Drive/Docs links from any specified webpage.
    *   Read links from a local text file.
*   **Command-Line Interface:** Control program behavior (scrape URL, use links file) via CLI arguments.
*   **Google Workspace Export:**
    *   Supports exporting Google Docs, Sheets, and Slides.
    *   Prompts user for desired export format (e.g., PDF, DOCX, XLSX) or uses configurable defaults.
    *   Caches format choices per session to avoid repetitive prompting.
*   **Concurrent Downloads:** Uses a thread pool to download multiple files simultaneously, significantly speeding up the process for many links.
*   **Robust Downloading:**
    *   Handles Google Drive's "large file" or "virus scan warning" confirmation pages.
    *   Streams downloads to efficiently handle large files without high memory usage.
    *   Extracts filenames from `Content-Disposition` headers or generates them.
    *   Sanitizes filenames to remove invalid characters.
    *   Automatically renames files if a file with the same name already exists in the download folder (appends `_1`, `_2`, etc.).
*   **Configuration File:** Centralized settings in `config.py` for easy customization.
*   **Detailed Logging:** Uses Python's `logging` module for informative output about the program's operations and any errors.

---
## 3. Prerequisites

*   **Python:** Version 3.7 or higher (due to use of `typing.Optional` and dataclasses).
*   **PIP:** Python package installer.
*   **Required Libraries:**
    *   `requests`: For making HTTP requests.
    *   `beautifulsoup4`: For parsing HTML (used in link scraping and handling GDrive confirmation pages).

---
## 4. Installation

1.  **Clone or Download:** Get the script files and place them in a directory on your system.
2.  **Install Dependencies:** Open your terminal or command prompt, navigate to the script's directory, and run:
    ```bash
    pip install requests beautifulsoup4
    ```
    It's recommended to do this within a Python virtual environment.

---
## 5. Directory Structure

Ensure all the Python files are in the same directory:

```
your_project_directory/
├── main.py               # Main execution script
├── config.py             # Configuration settings
├── link_extractor.py     # Extracts links from files or webpages
├── link_processor.py     # Processes URLs into downloadable tasks
├── downloader.py         # Handles the actual file downloading
├── utils.py              # Utility functions (filename sanitization, ID extraction)
├── datastructures.py     # Defines data classes (DownloadTask, DownloadResult)
├── links.txt             # Default file for URLs (created if not present)
└── downloaded_files/     # Default folder for downloaded files (created automatically)
```

---
## 6. Usage (Command Line)

The program is executed via \`main.py\`. You can specify the source of links (scrape a URL or use a file) through command-line arguments.

### Scraping a Webpage

To scrape Google Drive/Docs links from a specific webpage:

```bash
python main.py --scrape-url "YOUR_WEBPAGE_URL_HERE"
```

**Example:**

```bash
python main.py --scrape-url "URL"
```

The script will fetch the content of the provided URL, search for links matching patterns defined in \`config.GDOC_LINK_PATTERNS\`, and then attempt to download them.

### Using a Local Links File

To read URLs from a local text file (one URL per line):

```bash
python main.py --links-file "/path/to/your/links.txt"
```

**Example:**

```bash
python main.py --links-file "my_gdrive_links.txt"
```

If \`my_gdrive_links.txt\` contains:

```
https://docs.google.com/document/d/SOME_DOC_ID/edit
https://drive.google.com/file/d/SOME_FILE_ID/view
```

The script will process and download these links.

### Default Behavior (Using \`config.py\`)

If no command-line arguments for link sourcing are provided:

```bash
python main.py
```

The script will:
1.  First check if \`SCRAPE_URL\` is set in \`config.py\`. If it is, it will attempt to scrape that URL.
2.  If \`config.SCRAPE_URL\` is \`None\` (or not set), it will fall back to using the file specified by \`config.LINKS_FILE\` (defaulting to \`links.txt\` in the script's directory).
    *   If \`links.txt\` does not exist, a dummy \`links.txt\` with example URLs and comments will be created. You'll need to edit this file with your actual URLs and rerun the script.

### Getting Help

To see the available command-line options and a brief description:

```bash
python main.py --help
```

---
## 7. Configuration (\`config.py\`)

The \`config.py\` file allows you to customize various aspects of the program without modifying the core logic.

### Core Settings

*   \`DOWNLOAD_FOLDER = "downloaded_files"\`: The directory where downloaded files will be saved.
*   \`MAX_WORKERS = 5\`: The number of concurrent download threads. Adjust based on your internet connection and the server's capacity.
*   \`LINKS_FILE = "links.txt"\`: The default filename to read URLs from if no CLI source is specified and \`SCRAPE_URL\` is not set.

### Web Scraping Settings

*   \`SCRAPE_URL = None\`:
    *   Set this to a specific URL (e.g., \`"https://example.com/shared_files"\`) to enable scraping mode by default when no CLI arguments are given.
    *   If \`None\`, the script will use \`LINKS_FILE\` by default (unless overridden by CLI).
*   \`GDOC_LINK_PATTERNS\`: A list of regular expression patterns used by the \`LinkExtractor\` to identify potential Google Drive/Docs links on a webpage.
    ```python
    GDOC_LINK_PATTERNS = [
        r"drive\.google\.com/(?:file/d/|open\?id=|uc\?id=)([a-zA-Z0-9_-]+)",
        r"docs\.google\.com/(?:document|spreadsheets|presentation)/d/([a-zA-Z0-9_-]+)"
    ]
    ```

### Google Drive Export Settings

*   \`DEFAULT_DOC_FORMAT = "pdf"\`
*   \`DEFAULT_SHEET_FORMAT = "xlsx"\`
*   \`DEFAULT_SLIDES_FORMAT = "pptx"\`: Default export formats if the user doesn't specify one during the interactive prompt.
*   \`VALID_DOC_FORMATS\`, \`VALID_SHEET_FORMATS\`, \`VALID_SLIDES_FORMATS\`: Lists of valid export formats that the user can choose from.

### Logging Configuration

*   \`LOG_LEVEL = logging.INFO\`: The minimum severity level for log messages (e.g., \`logging.DEBUG\`, \`logging.INFO\`, \`logging.WARNING\`).
*   \`LOG_FORMAT = '%(asctime)s - %(levelname)s - [%(threadName)s] - %(message)s'\`: The format string for log messages.

### Request Settings

*   \`REQUEST_TIMEOUT = 30\`: General timeout (in seconds) for HTTP requests.
*   \`DOWNLOAD_TIMEOUT = 120\`: Timeout (in seconds) specifically for the data transfer part of a download, especially after a confirmation.
*   \`CHUNK_SIZE = 8192\`: Size (in bytes) of chunks to read when streaming downloads.
*   \`USER_AGENT\`: The User-Agent string sent with HTTP requests. Some sites might block default Python User-Agents.

---
## 8. How It Works (Workflow)

The program follows these general steps:

1.  **Initialization & Argument Parsing (\`main.py\`):**
    *   Parses command-line arguments to determine the source of links (scrape URL or links file).
    *   If no CLI arguments for source are given, it falls back to \`config.py\` settings (\`SCRAPE_URL\`, then \`LINKS_FILE\`).
    *   Initializes core components: \`LinkExtractor\`, \`LinkProcessor\`, \`Downloader\`.

2.  **Link Acquisition (\`LinkExtractor\`):**
    *   **If scraping:** Fetches the specified webpage, parses its HTML, and extracts all \`<a>\` tag \`href\` attributes that match the \`GDOC_LINK_PATTERNS\` from \`config.py\`.
    *   **If using a file:** Reads all non-empty, non-comment lines from the specified links file.
    *   A raw list of potential URLs is generated and deduplicated.

3.  **Link Processing (\`LinkProcessor\`):**
    *   Each unique URL is passed to \`LinkProcessor.process_link()\`.
    *   This method:
        *   Extracts the Google Drive File ID using \`utils.get_file_id_from_url()\`.
        *   Determines the type of link (direct file, Google Doc, Sheet, Slide, or folder).
        *   If it's an exportable type (Doc, Sheet, Slide):
            *   Calls \`_get_export_format()\` which prompts the user for the desired export format (e.g., PDF, DOCX).
            *   The chosen format is cached for the current session to avoid re-prompting for the same document type.
            *   Constructs the appropriate export URL.
        *   If it's a direct file, constructs the direct download URL.
        *   Folder links are skipped.
        *   Unrecognized links are skipped.
    *   If successful, a \`DownloadTask\` object (from \`datastructures.py\`) is created, containing all necessary information for downloading (original URL, download URL, file ID, filename hints, etc.).

4.  **Concurrent Downloading (\`Downloader\` & \`ThreadPoolExecutor\`):**
    *   A \`requests.Session\` is created to persist cookies and connection pooling.
    *   A \`ThreadPoolExecutor\` is used to manage a pool of worker threads (number defined by \`config.MAX_WORKERS\`).
    *   Each \`DownloadTask\` is submitted to the executor, which calls \`Downloader.download_file()\` in a separate thread.
    *   \`Downloader.download_file()\`:
        *   Makes an initial GET request to the \`download_url\` from the \`DownloadTask\`.
        *   **Handles Confirmation:** If the response is an HTML page indicating a GDrive confirmation (e.g., for large files or virus scans), it calls \`_handle_confirmation_page()\`.
            *   \`_handle_confirmation_page()\` parses the HTML to find the actual confirmation link/form and follows it.
        *   **Determines Filename:**
            *   Attempts to get the filename from the \`Content-Disposition\` header.
            *   If not available, uses the file ID and any known export extension as a base.
            *   Sanitizes the filename using \`utils.sanitize_filename()\`.
            *   Checks if a file with the same name already exists; if so, appends \`_1\`, \`_2\`, etc., to make it unique.
        *   **Streams Download:** Downloads the file in chunks (\`response.iter_content()\`) and writes it to the \`config.DOWNLOAD_FOLDER\`.
        *   Creates a \`DownloadResult\` object indicating success or failure, along with a message and filepath.

5.  **Reporting Results (\`main.py\`):**
    *   As each download task completes, its \`DownloadResult\` is collected.
    *   A summary of successful and failed downloads is printed to the console and logged.

---
## 9. Detailed Component Breakdown

### \`main.py\`

*   **Role:** The main entry point and orchestrator of the program.
*   **Key Functions:**
    *   \`main()\`:
        *   Sets up \`argparse\` for command-line argument handling.
        *   Determines the source of links (CLI args, \`config.SCRAPE_URL\`, or \`config.LINKS_FILE\`).
        *   Initializes \`LinkExtractor\`, \`LinkProcessor\`, and \`Downloader\`.
        *   Calls \`LinkExtractor\` to get the list of raw URLs.
        *   Iterates through URLs, calling \`LinkProcessor\` to create \`DownloadTask\` objects (this step involves user prompts for export formats if needed).
        *   Manages concurrent downloads using \`ThreadPoolExecutor\` and \`Downloader\`.
        *   Collects \`DownloadResult\` objects and prints a final summary.
    *   \`create_dummy_config_links_file_if_not_exists()\`: Helper to create \`links.txt\` if it's missing when the program defaults to using it.

### \`config.py\` (Details)

*   **Role:** Centralized configuration for the application. See [Configuration (\`config.py\`)](#configuration-configpy) section for details on specific variables.
*   **Importance:** Allows users to customize behavior without editing the core logic files.

### \`link_extractor.py\` (Class: \`LinkExtractor\`)

*   **Role:** Responsible for acquiring a list of URLs from a given source.
*   **Key Methods:**
    *   \`__init__(self, source_file_path=None)\`: Initializes with an optional path to a links file (used if reading from a file).
    *   \`get_links_from_file(self) -> list[str]\`:
        *   Reads URLs from the \`self.source_file_path\`.
        *   Skips empty lines and lines starting with \`#\` (comments).
        *   Returns a list of cleaned URLs.
    *   \`get_links_from_webpage(self, page_url: str, link_patterns: list[str]) -> list[str]\`:
        *   Takes a \`page_url\` and a list of \`link_patterns\` (regex).
        *   Uses \`requests.get()\` to fetch the HTML content of \`page_url\`.
        *   Uses \`BeautifulSoup\` to parse the HTML and find all \`<a>\` tags with \`href\` attributes.
        *   For each \`href\`:
            *   Resolves relative URLs to absolute URLs using \`urllib.parse.urljoin()\`.
            *   Normalizes the URL (removes fragments, ensures scheme).
            *   Checks if the \`full_url\` matches any of the provided \`link_patterns\` using \`re.search()\`.
        *   Returns a list of unique matching URLs.

### \`link_processor.py\` (Class: \`LinkProcessor\`)

*   **Role:** Takes a raw URL, validates it as a processable Google Drive/Docs link, determines its type, and prepares a \`DownloadTask\` object. Handles user interaction for choosing export formats.
*   **Key Attributes:**
    *   \`self.export_formats_cache = {}\`: A dictionary to cache the user's choice of export format for each document type (\`document\`, \`spreadsheet\`, \`presentation\`) during the current session. This avoids asking repeatedly for the same type.
*   **Key Methods:**
    *   \`_get_export_format(self, url_type: str) -> Optional[str]\`:
        *   Called for Google Docs, Sheets, or Slides.
        *   Checks \`self.export_formats_cache\` first.
        *   If not cached, prompts the user via \`input()\` to choose an export format from the \`VALID_..._FORMATS\` lists in \`config.py\`. Uses the \`DEFAULT_..._FORMAT\` from \`config.py\` if the user presses Enter.
        *   Validates the user's input.
        *   Caches and returns the chosen format.
    *   \`process_link(self, original_url: str) -> Optional[DownloadTask]\`:
        *   Uses \`utils.get_file_id_from_url()\` to extract the file ID.
        *   Identifies the link type based on URL structure:
            *   \`/file/d/\`: Standard GDrive file. Constructs a direct download URL (\`https://drive.google.com/uc?export=download&id={file_id}\`).
            *   \`/document/d/\`: Google Doc. Calls \`_get_export_format()\`, then constructs export URL (e.g., \`.../export?format=pdf\`).
            *   \`/spreadsheets/d/\`: Google Sheet. Similar to Docs.
            *   \`/presentation/d/\`: Google Slides. Similar to Docs.
            *   \`/drive/folders/\`: Skipped, as folders cannot be downloaded directly this way.
            *   Others: Unrecognized and skipped.
        *   If a valid downloadable link is identified, it creates and returns a \`DownloadTask\` object populated with \`original_url\`, \`file_id\`, the constructed \`download_url\`, \`filename_hint\`, \`file_extension\`, etc.
        *   Returns \`None\` if the link is not processable.

### \`downloader.py\` (Class: \`Downloader\`)

*   **Role:** Handles the actual downloading of a file based on a \`DownloadTask\`. Manages HTTP requests, GDrive confirmation pages, file I/O, and error handling during download.
*   **Key Methods:**
    *   \`__init__(self, download_folder: str)\`: Initializes with the path to the download folder and creates it if it doesn't exist.
    *   \`_handle_confirmation_page(self, response_text: str, session: requests.Session, original_url: str) -> Optional[requests.Response]\`:
        *   Parses the \`response_text\` (HTML of the confirmation page) using \`BeautifulSoup\`.
        *   Looks for a form with \`id="downloadForm"\` or an \`<a>\` tag with \`confirm=\` in its \`href\`.
        *   Constructs the confirmation URL and makes a new GET request using the provided \`session\` to follow it.
        *   Returns the \`requests.Response\` object for the actual file stream if successful, or \`None\` if bypass fails.
    *   \`download_file(self, task: DownloadTask, session: requests.Session) -> DownloadResult\`:
        *   Makes an initial GET request to \`task.download_url\` with \`stream=True\`.
        *   Checks if the response is an HTML confirmation page (e.g., by content type and keywords like "downloadForm"). If so, calls \`_handle_confirmation_page()\`.
        *   **Filename Determination:**
            *   Tries \`utils.get_filename_from_content_disposition(response.headers)\`.
            *   If not found, constructs a filename from \`task.filename_hint\` and \`task.file_extension\`.
            *   Sanitizes the filename using \`utils.sanitize_filename()\`.
            *   Checks for existing files: if \`filepath\` exists, appends \`_1\`, \`_2\`, etc., to the base filename until a unique name is found.
        *   **File Streaming:**
            *   Opens the target \`filepath\` in binary write mode (\`'wb'\`).
            *   Iterates over \`response.iter_content(chunk_size=config.CHUNK_SIZE)\` and writes each chunk to the file.
            *   Logs download progress internally (not a visible progress bar).
        *   Handles various \`requests.exceptions\` (HTTPError, ConnectionError, Timeout) and \`IOError\`.
        *   Ensures \`response.close()\` is called in a \`finally\` block to release the connection.
        *   Returns a \`DownloadResult\` object with success status, filepath, and a message.

### \`utils.py\`

*   **Role:** Contains miscellaneous helper functions used across different modules.
*   **Key Functions:**
    *   \`sanitize_filename(filename: str) -> str\`: Removes characters invalid for filenames (e.g., \`\ / : * ? " < > |\`), replaces spaces with underscores, and truncates long filenames.
    *   \`get_file_id_from_url(url: str) -> Optional[str]\`: Uses a list of regex patterns to extract the Google Drive file ID from various URL formats.
    *   \`get_filename_from_content_disposition(headers: dict) -> Optional[str]\`: Parses the \`Content-Disposition\` HTTP header to extract the filename, handling different encodings (like \`filename*=UTF-8''...\`).

### \`datastructures.py\`

*   **Role:** Defines simple data classes (using \`@dataclass\`) for structured data transfer between components.
*   **Key Classes:**
    *   \`DownloadTask\`: Represents a file to be downloaded.
        *   \`original_url: str\`
        *   \`file_id: str\`
        *   \`download_url: str\` (the URL to actually fetch the file content)
        *   \`filename_hint: str\` (initial guess for filename, often the file ID)
        *   \`file_extension: str\` (e.g., ".pdf", ".docx" if known from export)
        *   \`is_export: bool\`
        *   \`export_format: Optional[str]\`
        *   \`cookies: Dict[str, str]\` (currently unused, as session handles cookies)
    *   \`DownloadResult\`: Represents the outcome of a download attempt.
        *   \`original_url: str\`
        *   \`success: bool\`
        *   \`filepath: Optional[str]\` (path to the downloaded file if successful)
        *   \`message: str\` (summary message, e.g., "Success: filename.pdf" or "Failed: HTTP Error 404")
        *   \`error: Optional[Exception]\` (the exception object if an error occurred)

---
## 10. Error Handling and Logging

*   **Error Handling:**
    *   The \`downloader.py\` module contains extensive \`try-except\` blocks to catch common issues during HTTP requests and file I/O (e.g., \`requests.exceptions.HTTPError\`, \`ConnectionError\`, \`Timeout\`, \`IOError\`).
    *   Failures are encapsulated in \`DownloadResult\` objects, allowing the main loop to report them without crashing.
    *   \`LinkProcessor\` handles invalid or unprocessable URLs gracefully by returning \`None\`.
*   **Logging:**
    *   The script uses Python's built-in \`logging\` module.
    *   Log messages are printed to the console.
    *   Log level and format are configurable in \`config.py\` (\`LOG_LEVEL\`, \`LOG_FORMAT\`).
    *   Includes timestamps, log levels, thread names (useful for concurrent operations), and messages.
    *   Helps in diagnosing issues, understanding the program flow, and seeing which files succeeded or failed.

---
## 11. Troubleshooting Common Issues

*   **No Links Found When Scraping:**
    *   **Cause:** The target webpage might load content dynamically using JavaScript. This scraper (using \`requests\` + \`BeautifulSoup\`) only sees the initial HTML.
    *   **Solution:** For dynamic sites, you might need tools like \`Selenium\` or \`requests-html\`.
    *   **Cause:** The \`GDOC_LINK_PATTERNS\` in \`config.py\` might not match the URL structure on the specific website.
    *   **Solution:** Inspect the webpage's source code and adjust the regex patterns accordingly.
*   **Download Failures (e.g., 403 Forbidden, 404 Not Found):**
    *   **Cause:** The link might be private, expired, or require specific permissions/login that the script doesn't handle.
    *   **Solution:** Ensure the links are publicly accessible or that you have the necessary access if a session-based approach were implemented for authenticated downloads (current script assumes public links).
    *   **Cause:** Google might have changed its download mechanisms or URL structures.
    *   **Solution:** The script, especially \`LinkProcessor\` and \`Downloader\`'s confirmation handling, might need updates.
*   **"NameError: name 'Optional' is not defined" (or similar for other types):**
    *   **Cause:** A type hint (e.g., \`Optional\`, \`List\`, \`Dict\`) from the \`typing\` module was used without importing it.
    *   **Solution:** Add the necessary import, e.g., \`from typing import Optional, List, Dict\` at the top of the affected Python file.
*   **Files Not Downloading / 0-byte Files:**
    *   **Cause:** Could be an undetected error page being saved, or an issue with the confirmation bypass.
    *   **Solution:** Check logs carefully. Increase \`LOG_LEVEL\` to \`DEBUG\` in \`config.py\` for more detailed output.
*   **Permission Denied When Writing Files:**
    *   **Cause:** The script doesn't have write permissions for the \`DOWNLOAD_FOLDER\`.
    *   **Solution:** Ensure the user running the script has write access to the target directory, or change \`DOWNLOAD_FOLDER\` in \`config.py\` to a writable location.

---
## 12. Future Enhancements

*   **GUI:** Develop a graphical user interface (e.g., using Tkinter, PyQt, Kivy) for easier use.
*   **Advanced Progress Reporting:** Implement a visual progress bar (e.g., using \`tqdm\`) for downloads.
*   **Recursive Scraping:** Option to scrape links from a starting URL and follow links to other pages on the same domain up to a certain depth.
*   **Retry Mechanism:** Implement automatic retries for failed downloads due to transient network issues.
*   **Authenticated Downloads:** Add support for logging into Google to download private files (this is complex due to authentication flows like OAuth2).
*   **More Granular Configuration via CLI:** Allow overriding more \`config.py\` settings (like export formats, download folder) directly from the command line.
*   **Support for Other Cloud Services:** Extend the framework to support downloading from other services like Dropbox, OneDrive, etc.
*   **Unit Tests:** Add comprehensive unit tests for individual components to ensure reliability and easier refactoring.