"""
Madison-County deed puller
──────────────────────────
• 237 < Book < 3972  →  uses the “MID” portal
• everything else    →  uses the Historical Books portal

After each download the file is renamed   Book-Page.pdf
then moved into  /path/to/spreadsheet/Docs/
"""

import os, time, shutil
import pandas as pd
from pathlib import Path
import logging
import os # For path sanitization if needed
import time # For timestamping snapshots
from pathlib import Path # Already imported, but good to note for snap function
# ... other existing imports ...
# from selenium.webdriver.common.desired_capabilities import DesiredCapabilities # For logging prefs # Removed as per previous instructions if not used
# from seleniumwire import webdriver as wire # Optional: for HAR file, uncomment if selenium-wire is installed

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from tkinter import Tk
from tkinter.filedialog import askopenfilename
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service as ChromeService # Corrected import for Service
from selenium.webdriver.common.action_chains import ActionChains

# Configure logging at the beginning of your script
# Ensure this path is appropriate for your environment.
# It will create the log file in the same directory as the script.
log_file_path = Path(__file__).parent / 'madison_county_deed_puller.log'
level = logging.DEBUG if os.getenv("MC_DEBUG") == "1" else logging.INFO
logging.basicConfig(
    level=level,
    format='%(asctime)s - %(levelname)s - %(funcName)s - Line %(lineno)d - %(message)s',
    filename=log_file_path,
    filemode='w'  # 'w' to overwrite the log file each run, 'a' to append
)

# Helper function for snapshots
def snap(driver, tag):
    """Saves a screenshot and HTML snapshot for debugging."""
    try:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        # Ensure debug_snaps directory is relative to the script file
        folder = Path(__file__).parent / "debug_snaps"
        folder.mkdir(exist_ok=True)
        screenshot_path = folder / f"{stamp}_{tag}.png"
        html_path = folder / f"{stamp}_{tag}.html"
        
        driver.save_screenshot(str(screenshot_path))
        time.sleep(1) # Added
        logging.info(f"Saved snapshot (screenshot): {screenshot_path}")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        logging.info(f"Saved snapshot (HTML): {html_path}")
    except Exception as e:
        logging.error(f"Failed to save snapshot with tag '{tag}': {e}", exc_info=True)

# Helper function for process_spreadsheet_entries
def sanitize(text: str) -> str:
    """Return a filesystem-safe string (alnum + “_”)."""
    return "".join(c if c.isalnum() else "_" for c in text)

def click_when_visible(driver, locator):
    """Wait until *locator* is visible & enabled, scroll it into view, then .click()."""
    el = WebDriverWait(driver, WAIT).until(
        EC.element_to_be_clickable(locator)
    )
    ActionChains(driver).move_to_element(el).pause(0.2).click(el).perform()
    return el

def first_grid_row(driver):
    """Return <td> of the first search result (column 3)."""
    return WebDriverWait(driver, WAIT).until(
        EC.element_to_be_clickable((By.XPATH, "//table[@id='grid']/tbody/tr[1]/td[3]"))
    )

OLD = ("https://tools.madison-co.net/elected-offices/chancery-clerk/"
       "drupal-search-historical-books/?type=deed&method=bookpage")
MID = ("https://tools.madison-co.net/elected-offices/chancery-clerk/"
       "court-house-search/drupal-deed-record-lookup.php")
NEW = "https://records.madison-co.com/DuProcesswebinquiry"

# credentials for DuProcess –- keep them out of the repo
DUP_USER     = "gardner@maplesrichey.com"
DUP_P = "3xDpbedN3MN2GJx"

WAIT = 10  # seconds – explicit-wait budget


# ───────────────────────── helpers ──────────────────────────
def get_spreadsheet_path() -> str:
    Tk().withdraw()
    return askopenfilename(
        title="Select Spreadsheet",
        filetypes=[("Spreadsheet Files", "*.csv *.xls *.xlsx")]
    )


def parse_book(book_raw: str) -> tuple[int | None, str]:
    """
    Split the spreadsheet’s Book field into

        (numeric_part_or_None, prefix)

    Examples
    --------
    "240"        -> (240, "")
    "DT 502"     -> (502, "DT")
    "DDD"        -> (None, "DDD")
    """
    parts = book_raw.strip().upper().split()
    if not parts: # Handle empty string case
        return None, ""
    if parts[0].isdigit():                 # plain number
        return int(parts[0]), ""
    if len(parts) == 2 and parts[1].isdigit():
        return int(parts[1]), parts[0]     # e.g. "DT 502"
    return None, parts[0]                  # DDD, AA, etc.


def doc_type_for(book_raw: str) -> str:
    """
    Return the MID site’s doc_type code for this book string.
    We only care about DEED (01) and DEED OF TRUST (02).
    """
    _, prefix = parse_book(book_raw)
    return "02" if prefix == "DT" else "01"


def choose_portal(book_raw: str) -> str:
    """
    Decide which site to hit *and* do basic validation.
    """
    num, prefix = parse_book(book_raw)

    if num and num >= 3972:
        return NEW           # “new” site
    if num and 237 < num < 3972:
        return MID           # direct-URL site
    return OLD               # historical dropdown site


def wait_for(driver, by, value):
    return WebDriverWait(driver, WAIT).until(
        EC.presence_of_element_located((by, value))
    )

# Renamed and generalized function
def get_driver_logs(driver, log_type: str, context_message=""):
    logging.info(f"Fetching '{log_type}' logs: {context_message}")
    try:
        log_entries = driver.get_log(log_type)
        for entry in log_entries:
            logging.info(f"Selenium Log ({log_type}): {entry['level']} - {entry['message']}")
            if 'source' in entry and entry['source']:
                logging.debug(f"  Source: {entry['source']}")
            if 'timestamp' in entry:
                logging.debug(f"  Timestamp: {entry['timestamp']}")
    except Exception as e:
        logging.warning(f"Could not fetch '{log_type}' logs: {e}")


# ───────────────────────── driver factory (Chrome) ──────────────────────────
def init_driver(download_dir: Path) -> webdriver.Chrome:
    """Return a Chrome WebDriver that auto-downloads PDFs to *download_dir*."""
    logging.info(f"Initializing Chrome driver. Download directory: {download_dir}")
    chrome_prefs = {
        "download.default_directory": str(download_dir),
        "download.prompt_for_download": False,
        "plugins.always_open_pdf_externally": True,      # bypass PDF viewer
        "profile.default_content_setting_values.automatic_download": 1,
    }

    options = Options()
    options.add_experimental_option("prefs", chrome_prefs)
    options.add_argument("--disable-popup-blocking")
    # options.add_argument("--headless=new")             # <- uncomment for headless

    # Set up desired capabilities for extensive logging
    options.set_capability(
        "goog:loggingPrefs",
        {"browser": "ALL", "performance": "ALL"}
    )
    logging.info("Browser and performance logging enabled via options.set_capability.")

    # Enable verbose logging for ChromeDriver
    chrome_driver_log_path = Path(__file__).parent / "chromedriver_verbose.log"
    
    # For selenium-wire (optional HAR generation)
    # from seleniumwire import webdriver as wire # Uncomment if using selenium-wire
    # selenium_wire_options = {} # Define selenium-wire specific options if needed

    try:
        # Ensure log_output is a string for ChromeService
        service = ChromeService(log_output=str(chrome_driver_log_path), service_args=['--verbose'])
        logging.info(f"ChromeDriver verbose logging configured to: {chrome_driver_log_path}")
        # Pass only service and options to the driver constructor
        # driver = wire.Chrome(service=service, options=options, seleniumwire_options=selenium_wire_options) # For selenium-wire
        driver = webdriver.Chrome(service=service, options=options)
    except Exception as e:
        logging.error(f"Failed to initialize ChromeService with verbose logging: {e}. Falling back.")
        # Fallback if specific ChromeService setup fails
        # driver = wire.Chrome(options=options, seleniumwire_options=selenium_wire_options) # For selenium-wire fallback
        driver = webdriver.Chrome(options=options) # Standard fallback
    
    # If using selenium-wire, set scopes after driver initialization
    # if isinstance(driver, wire.webdriver.WebDriver):
    #     driver.scopes = ['.*\\/DuProcessWebInquiry\\/.*'] # Focus on this domain
    #     logging.info("Selenium-wire scopes set for DuProcessWebInquiry.")

    logging.info("Chrome driver initialized.")
    return driver


def wait_for_download(download_dir: Path, before: set, timeout: int = 30) -> Path:
    """Block until a new, fully-written file appears in *download_dir*."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        current = set(p for p in download_dir.iterdir() if p.suffix != ".part")
        new_files = current - before
        if new_files:
            return new_files.pop()
        time.sleep(0.5)
    raise TimeoutError("Timed-out waiting for download to complete.")


# ───────────────────────── portal workflows ──────────────────────────
def historical(driver, book: str, page: str):
    driver.get(OLD)

    # 1️⃣  Pick the book immediately
    Select(wait_for(driver, By.ID, "book")).select_by_visible_text(book)

    # 2️⃣  WAIT until that <select id="page"> actually contains our page
    def page_ready(drv):
        try:
            return any(opt.text == page
                       for opt in Select(drv.find_element(By.ID, "page")).options)
        except Exception:   # element not present yet
            return False

    WebDriverWait(driver, WAIT).until(page_ready)

    # 3️⃣  Now the option is definitely there
    Select(driver.find_element(By.ID, "page")).select_by_visible_text(page)

    wait_for(driver, By.ID, "submit").click()


def mid(driver, book_raw: str, page: str):
    """
    Build the one-shot URL and download the first image.

    * No form-filling, no iframes.
    * We click the first <a> whose href contains 'pdf-records.php?image='.
    """
    num, _ = parse_book(book_raw)
    if not num:
        # This case should ideally be handled by choose_portal routing to OLD
        # but as a safeguard:
        raise ValueError(f"Book '{book_raw}' is not numeric and was incorrectly routed to MID site.")

    # Construct the query URL for the MID portal
    # The base URL is hardcoded here as per the provided example.
    # Ensure the MID constant is also updated if it's used for other purposes.
    query = (
        "https://tools.madison-co.net/elected-offices/chancery-clerk/"
        "court-house-search/drupal-deed-record-lookup.php"
        f"?doc_type={doc_type_for(book_raw)}"
        f"&book={num}"
        f"&bpage={page}"
        "&do_search=Submit+Query"
    )

    driver.get(query)

    # The first “Download Image 1” link is what we want
    # It might be inside an h3, so a more general selector is used.
    pdf_link = WebDriverWait(driver, WAIT).until(
        EC.element_to_be_clickable(
            (By.CSS_SELECTOR, "a[href*='pdf-records.php?image=']")
        )
    )
    pdf_link.click()
    # Note: The original mid function had driver.switch_to.default_content()
    # This is not needed here as we are not interacting with iframes in this new approach.


du_logged_in = False      # module-level flag

def duprocess_login(driver):
    global du_logged_in
    if du_logged_in:
        return

    driver.get(NEW)

    # 1. Accept the disclaimer
    WebDriverWait(driver, WAIT).until(
        EC.element_to_be_clickable((By.ID, "instruction_agreement_button"))
    ).click()

    # 2. Open login modal
    WebDriverWait(driver, WAIT).until(
        EC.element_to_be_clickable((By.ID, "login_link"))
    ).click()
    logging.debug("Login link clicked.")

    # 3. Enter e-mail + password
    logging.debug("Attempting to enter login credentials.")
    WebDriverWait(driver, WAIT).until(
        EC.visibility_of_element_located((By.ID, "login_email"))
    ).send_keys(DUP_USER)
    driver.find_element(By.ID, "login_password").send_keys(DUP_P)
    logging.info(f"Entered username: {DUP_USER}")

    # 4. Click <button> inside the color-box modal
    # More specific selector for the login button if possible, e.g., based on text or a more unique attribute
    login_button_selector = "div#cboxLoadedContent button[type='submit']" # Example, adjust if needed
    try:
        # Try a more specific selector first
        login_button = WebDriverWait(driver, WAIT).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, login_button_selector))
        )
        logging.debug(f"Login button found with selector: {login_button_selector}")
    except:
        # Fallback to the original selector if the specific one fails
        logging.warning(f"Specific login button selector '{login_button_selector}' failed, trying original.")
        login_button_selector = "div#cboxLoadedContent button" # Original selector
        login_button = WebDriverWait(driver, WAIT).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, login_button_selector))
        )
        logging.debug(f"Login button found with selector: {login_button_selector}")
    
    login_button.click()
    logging.info("Login button clicked.")

    # 5. Wait until the modal disappears
    logging.debug("Waiting for login modal (colorbox) to disappear.")
    WebDriverWait(driver, WAIT).until(
        EC.invisibility_of_element_located((By.ID, "colorbox"))
    )
    logging.info("Login modal disappeared & context reset.")

    du_logged_in = True


def wait_overlay_gone(driver, timeout=8):
    """Block until #cboxOverlay is truly not visible/displayed."""
    time.sleep(0.5)
    try:
        WebDriverWait(driver, timeout).until(
            lambda d: not d.find_element(By.ID, "cboxOverlay").is_displayed()
        )
    except Exception:
        pass   # overlay element absent -> OK


def wait_parent_panel_clear(driver, timeout=10):
    """Block until the search overlay is truly gone or fully transparent."""
    def cleared(_):
        try:
            pp = driver.find_element(By.ID, "parent_panel")
            return driver.execute_script(
                "return window.getComputedStyle(arguments[0]).opacity;", pp
            ) in ("0", 0)
        except Exception:          # element vanished
            return True
    time.sleep(0.5)
    WebDriverWait(driver, timeout).until(cleared)


def click_first_result(driver):
    """Clicks the first instrument row after the search overlay disappears."""
    time.sleep(0.5)
    first_td = WebDriverWait(driver, WAIT).until(
       EC.element_to_be_clickable((By.XPATH, "//*[@id='grid']/tbody/tr[1]/td[3]"))
       )
    ActionChains(driver).move_to_element(first_td).pause(0.2).click().perform()


def duprocess_add_to_cart(driver, book_raw: str, page: str):
    """Enter Book / Page, run the search, add the first hit to the cart."""
    num_book, _ = parse_book(book_raw)
    if num_book is None:
        raise ValueError(f"Book “{book_raw}” is not numeric")

    # make sure the criteria panel is open
    try:
        driver.find_element(By.CSS_SELECTOR,
            "#criteria_panel .minimized_view").click()          # expand if collapsed
    except Exception:
        pass                                                   # already open

    # clear any previous criteria
    clear = driver.find_element(By.ID, "clear_button")
    if clear.is_enabled():
        clear.click()

    # -----  type book / page -------------------------------------------------
    for field_id, value in (("criteria_book_reel", num_book),
                            ("criteria_page_image", page)):
        box = WebDriverWait(driver, WAIT).until(
            EC.element_to_be_clickable((By.ID, field_id)))
        box.clear()
        box.send_keys(str(value))

    # -----  run the search ---------------------------------------------------
    driver.find_element(By.ID, "search_button").click()

    # grid is populated when the first row’s 3rd cell exists
    row_cell = WebDriverWait(driver, WAIT).until(
        EC.element_to_be_clickable((By.XPATH, "//*[@id='grid']/tbody/tr[1]/td[3]")))
    row_cell.click()

    # -----  add to cart ------------------------------------------------------
    WebDriverWait(driver, WAIT).until(
        EC.element_to_be_clickable((By.ID, "purchase_icon"))).click()

    WebDriverWait(driver, WAIT).until(
        EC.element_to_be_clickable((By.ID, "purchase_copy_button"))).click()

    # the confirm modal has only two buttons – the second one is “OK”
    WebDriverWait(driver, WAIT).until(
        EC.element_to_be_clickable(
            (By.XPATH, "//div[@id='cboxLoadedContent']/div/button[2]"))).click()

    WebDriverWait(driver, WAIT).until(
        lambda d: int(d.find_element(By.ID, "items_in_cart_count").text) > 0)
    
    try:
        driver.find_element(
            By.CSS_SELECTOR, "#criteria_panel .minimized_view"
            ).click()
        logging.debug("Criteria panel re-expanded for next iteration.")
    except Exception:
        # panel was already open – nothing to do
        pass


def duprocess_close_viewer_if_open(driver):
    try:
        # Wait a short moment for the close button to be potentially interactable
        close_btn = WebDriverWait(driver, 3).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "div.viewer-panel img[title='Close']"))
        )
        close_btn.click()
        WebDriverWait(driver, 3).until(
            EC.invisibility_of_element_located((By.CSS_SELECTOR, 'div.viewer-panel')))
    except Exception:
        pass # PDF viewer not open or close button not found


# ───────────────────────── main loop ──────────────────────────
def process_spreadsheet_entries():
    sheet_path = Path(get_spreadsheet_path())
    if not sheet_path:
        print("No file selected – exiting."); return

    df = (pd.read_csv(sheet_path) if sheet_path.suffix == ".csv"
          else pd.read_excel(sheet_path))

    if {"Book", "Page"} - set(df.columns):
        raise ValueError("Spreadsheet must contain 'Book' and 'Page' columns.")

    # destinations
    docs_dir = sheet_path.parent / "Docs"
    docs_dir.mkdir(exist_ok=True)
    download_dir = docs_dir.parent / "_tmp_downloads"
    download_dir.mkdir(exist_ok=True)
    failed_log_path = docs_dir / "failed_downloads.txt"

    # Clear the log file at the beginning of a new run
    if failed_log_path.exists():
        failed_log_path.unlink()

    driver = init_driver(download_dir)

    try:
        for i, row in df.iterrows():
            raw_book, raw_page = str(row["Book"]).strip(), str(row["Page"]).strip()
            if not raw_book or not raw_page:
                message = f"Row {i+2}: missing Book/Page – skipped."
                print(message)
                with open(failed_log_path, "a") as f_log:
                    f_log.write(f"Skipped Row {i+2}: Missing Book/Page\n")
                continue

            portal = choose_portal(raw_book) # Use raw_book directly
            logging.debug("Routing Book %s to portal %s", raw_book, portal)
            print(f"[{i+1}/{len(df)}] Book {raw_book}, Page {raw_page} → {portal.split('/')[2]}")

            # capture directory state *before* download
            before_files = set(p for p in download_dir.iterdir())

            origin = driver.current_window_handle
            try:
                # portal is already defined by choose_portal(raw_book) before this try block
                if portal == NEW:
                    duprocess_login(driver)
                    duprocess_add_to_cart(driver, raw_book, raw_page)
                elif portal == MID:
                    mid(driver, raw_book, raw_page)          # unchanged
                else: # portal is OLD
                    historical(driver, raw_book, raw_page)   # unchanged
                logging.info(f"Successfully processed Book {raw_book}, Page {raw_page} via {portal}.")
            except Exception as e:
                logging.error(f"Exception occurred processing Book {raw_book}, Page {raw_page}", exc_info=True)
                get_driver_logs(driver, 'browser', f"Error state for Book {raw_book}, Page {raw_page}")
                get_driver_logs(driver, 'performance', f"Error state for Book {raw_book}, Page {raw_page}")
                
                sane_book = sanitize(raw_book)
                sane_page = sanitize(raw_page)
                snap_tag = f"error_B{sane_book}_P{sane_page}_{type(e).__name__}"
                snap(driver, snap_tag) # snap writes the file for you
                with open(failed_log_path, "a") as f_log:
                    f_log.write(f"Book {raw_book}, Page {raw_page} - Selenium Error: {e}\n")
                # Attempt to close viewer if open, even on error, before continuing
                if portal == NEW:
                    duprocess_close_viewer_if_open(driver)
                continue

            # some portals spawn a new tab; close it after the file appears
            # For NEW portal, items are added to cart, no direct download expected here.
            # For MID and OLD, a download is expected.
            if portal in (MID, OLD):
                try:
                    downloaded = wait_for_download(download_dir, before_files)
                    new_name = f"{raw_book}-{raw_page}.pdf" # Ensure raw_book is suitable for filename
                    final_path = docs_dir / new_name
                    shutil.move(downloaded, final_path)
                    # If MID or OLD portal might open a PDF viewer that needs closing, add call here
                    # Example: if portal is MID: duprocess_close_viewer_if_open(driver)
                    # However, the prompt only specifies this for the NEW portal's workflow.
                except Exception as e:
                    message = f" ⚠️  Download-handling error on Book {raw_book}, Page {raw_page}: {e}"
                    print(message)
                    with open(failed_log_path, "a") as f_log:
                        f_log.write(f"Book {raw_book}, Page {raw_page} - Download/Move Error: {e}\n")
                    # Even if download fails, try to clean up tabs
                    handles = driver.window_handles
                    for h in handles[1:]:
                        driver.switch_to.window(h)
                        driver.close()
                    if handles:
                        driver.switch_to.window(handles[0])
                    continue # Continue to next item in spreadsheet
            elif portal == NEW:
                # For the NEW portal, after adding to cart, we might want to close a viewer if it opened.
                # The prompt suggests calling it after wait_for_download, but for NEW portal,
                # there isn't a wait_for_download in the same way.
                # The duprocess_add_to_cart already tries to close it at the beginning.
                # However, if a preview was opened by other means and not closed,
                # this call ensures it's closed before the next iteration.
                duprocess_close_viewer_if_open(driver)
                # No file move for NEW portal as items are added to cart for later checkout.
            # time.sleep(1)     # polite one-second pause (optional)

    finally:
        # If using selenium-wire, export HAR file
        # if isinstance(driver, wire.webdriver.WebDriver):
        #     try:
        #         har_path = Path(__file__).parent / "duprocess.har"
        #         driver.har_export(str(har_path))
        #         logging.info(f"HAR file exported to {har_path}")
        #     except Exception as har_e:
        #         logging.error(f"Failed to export HAR file: {har_e}")
        
        if driver: # Ensure driver exists before quitting
            time.sleep(60)
            driver.quit()
            logging.info("Browser driver quit.")
        # tidy up the temp directory (leave the Docs folder intact)
        shutil.rmtree(download_dir, ignore_errors=True)
        print("All done. PDFs collected in:", docs_dir)
        if failed_log_path.exists() and os.path.getsize(failed_log_path) > 0:
            print(f"Some downloads failed. See {failed_log_path} for details.")
        else:
            # Optionally remove the log file if it's empty
            if failed_log_path.exists():
                failed_log_path.unlink()


if __name__ == "__main__":
    process_spreadsheet_entries()
