# main.py
import logging
import os
import argparse # New import
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

import config
from link_extractor import LinkExtractor
from link_processor import LinkProcessor
from downloader import Downloader
from datastructures import DownloadResult, DownloadTask

# Setup basic logging
logging.basicConfig(level=config.LOG_LEVEL, format=config.LOG_FORMAT, datefmt='%Y-%m-%d %H:%M:%S')
logger = logging.getLogger(__name__)

# Quieten noisy libraries
logging.getLogger("requests").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("charset_normalizer").setLevel(logging.WARNING)


def create_dummy_config_links_file_if_not_exists():
    """Creates the default links.txt (from config) if it doesn't exist."""
    if not os.path.exists(config.LINKS_FILE):
        logger.warning(f"Default links file '{config.LINKS_FILE}' not found. Creating a dummy file.")
        with open(config.LINKS_FILE, "w", encoding="utf-8") as f:
            f.write("# Add Google Drive URLs below, one per line.\n")
            f.write("# This file is used if no command-line source is specified AND SCRAPE_URL in config.py is not set.\n")
            f.write("# Example file:\n")
            f.write("# https://drive.google.com/file/d/YOUR_FILE_ID_HERE/view?usp=sharing\n")
            f.write("# Example Google Doc (will prompt for export format):\n")
            f.write("# https://docs.google.com/document/d/YOUR_DOC_ID_HERE/edit?usp=sharing\n")
        logger.info(f"Dummy '{config.LINKS_FILE}' created. Please edit it with actual URLs or use command-line options.")
        return False # Indicates user should edit it or that it was just created
    return True # File exists

def main():
    logger.info("Starting Google Drive Downloader Program")

    parser = argparse.ArgumentParser(
        description="Downloads Google Drive/Docs files. Links can be sourced from a webpage or a local file.",
        formatter_class=argparse.RawTextHelpFormatter # For better help text formatting
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        '--scrape-url',
        type=str,
        metavar='URL',
        help="URL of the webpage to scrape for GDrive/Docs links."
    )
    group.add_argument(
        '--links-file',
        type=str,
        metavar='FILE_PATH',
        help="Path to a local file containing GDrive/Docs URLs, one per line."
    )
    # Example of how other configs could be exposed via CLI:
    # parser.add_argument(
    #     '--download-folder',
    #     type=str,
    #     default=config.DOWNLOAD_FOLDER,
    #     help=f"Folder to save downloaded files (default: {config.DOWNLOAD_FOLDER})"
    # )
    # parser.add_argument(
    #     '--max-workers',
    #     type=int,
    #     default=config.MAX_WORKERS,
    #     help=f"Number of concurrent downloads (default: {config.MAX_WORKERS})"
    # )

    args = parser.parse_args()

    # Determine operation mode and source
    # Precedence: CLI args > config.SCRAPE_URL > config.LINKS_FILE
    actual_scrape_url = None
    actual_links_file = None
    operation_mode_source = "" # e.g., "scrape_cli", "file_config"

    if args.scrape_url:
        actual_scrape_url = args.scrape_url
        operation_mode_source = "scrape_cli"
    elif args.links_file:
        actual_links_file = args.links_file
        operation_mode_source = "file_cli"
    elif config.SCRAPE_URL: # Fallback to SCRAPE_URL in config.py
        actual_scrape_url = config.SCRAPE_URL
        operation_mode_source = "scrape_config"
    else: # Fallback to LINKS_FILE in config.py
        actual_links_file = config.LINKS_FILE
        operation_mode_source = "file_config"

    # Initialize components
    # LinkExtractor is initialized with source_file_path if operating in file mode
    link_extractor = LinkExtractor(source_file_path=actual_links_file if actual_links_file else None)
    link_processor = LinkProcessor()
    downloader = Downloader(download_folder=config.DOWNLOAD_FOLDER) # Using DOWNLOAD_FOLDER from config.py

    urls_to_process_raw = []

    if actual_scrape_url:
        mode_name = "CLI" if "cli" in operation_mode_source else "config.py"
        logger.info(f"Mode: Scraping URL (source: {mode_name}). Target: {actual_scrape_url}")
        logger.info(f"Using GDrive link patterns: {config.GDOC_LINK_PATTERNS}")
        scraped_links = link_extractor.get_links_from_webpage(
            actual_scrape_url,
            config.GDOC_LINK_PATTERNS
        )
        if not scraped_links:
            logger.warning(f"No links matching GDrive patterns found on {actual_scrape_url}")
        else:
            logger.info(f"Found {len(scraped_links)} potential GDrive/Docs links from {actual_scrape_url}")
        urls_to_process_raw.extend(scraped_links)

    elif actual_links_file:
        mode_name = "CLI" if "cli" in operation_mode_source else "config.py"
        logger.info(f"Mode: Reading from links file (source: {mode_name}). Path: {actual_links_file}")

        if operation_mode_source == "file_config": # Only create dummy for the default config file
            create_dummy_config_links_file_if_not_exists() # Try to create if not exists

        if not os.path.exists(actual_links_file):
            logger.error(f"Links file not found: {actual_links_file}")
            if operation_mode_source == "file_config":
                 logger.error("Please populate it or use command-line options (--scrape-url or --links-file).")
            return # Exit if file doesn't exist

        file_links = link_extractor.get_links_from_file() # LinkExtractor already has the path
        if not file_links:
            logger.warning(f"No links found in {actual_links_file}. Ensure it's populated.")
        urls_to_process_raw.extend(file_links)
    else:
        # This case should ideally not be reached if logic is correct
        logger.error("No source for links determined (CLI, config.SCRAPE_URL, or config.LINKS_FILE). Please check configuration or arguments.")
        parser.print_help()
        return

    if not urls_to_process_raw:
        logger.info("No URLs to process (either from file or scraping). Exiting.")
        return

    unique_urls = sorted(list(set(urls_to_process_raw)))
    if len(unique_urls) < len(urls_to_process_raw):
        logger.info(f"Removed {len(urls_to_process_raw) - len(unique_urls)} duplicate URLs.")
    
    logger.info(f"Total unique URLs to process: {len(unique_urls)}")

    # 3. Process links to create DownloadTasks
    download_tasks: list[DownloadTask] = []
    logger.info("Processing links to prepare for download (this may involve prompts for export formats)...")
    for url in unique_urls:
        task = link_processor.process_link(url)
        if task:
            download_tasks.append(task)
    
    if not download_tasks:
        logger.info("No valid download tasks generated from the provided/scraped URLs. Exiting.")
        return

    logger.info(f"Prepared {len(download_tasks)} tasks for download.")

    # 4. Execute downloads concurrently
    results: list[DownloadResult] = []
    
    with requests.Session() as session:
        session.headers.update({"User-Agent": config.USER_AGENT})
        # Using MAX_WORKERS from config.py. Could be overridden by args if added to parser.
        with ThreadPoolExecutor(max_workers=config.MAX_WORKERS) as executor:
            future_to_task = {
                executor.submit(downloader.download_file, task, session): task 
                for task in download_tasks
            }

            processed_count = 0
            for future in as_completed(future_to_task):
                processed_count += 1
                task = future_to_task[future]
                try:
                    result = future.result()
                    results.append(result)
                    logger.info(f"Progress: ({processed_count}/{len(download_tasks)}) Processed {task.original_url}")
                    if result.success:
                        logger.info(f"  -> SUCCESS: {result.message}")
                    else:
                        logger.error(f"  -> FAILURE: {result.message}")
                except Exception as exc:
                    logger.error(f"Task for {task.original_url} generated an unhandled exception: {exc}", exc_info=True)
                    results.append(DownloadResult(original_url=task.original_url, success=False, message=f"Unhandled exception: {exc}"))

    # 5. Report summary
    logger.info("\n--- Download Summary ---")
    successful_downloads = 0
    failed_downloads = []
    for res in results:
        if res.success:
            logger.info(f"SUCCESS: {res.filepath if res.filepath else 'N/A'} (from {res.original_url})")
            successful_downloads += 1
        else:
            logger.error(f"FAILED: {res.message} (URL: {res.original_url})")
            failed_downloads.append(res)
    
    logger.info(f"\nFinished. {successful_downloads}/{len(download_tasks)} tasks completed successfully.")
    if failed_downloads:
        logger.warning(f"{len(failed_downloads)} tasks failed. See logs above for details.")
    logger.info(f"Files are in: {os.path.abspath(config.DOWNLOAD_FOLDER)}")

if __name__ == "__main__":
    main()