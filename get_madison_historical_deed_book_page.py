import pandas as pd
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

def scrape_madison_county():
    # Create a Chrome browser instance
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()))
    
    try:
        # Navigate directly to the book/page search URL
        print("Loading direct URL...")
        # Wills
        driver.get("https://tools.madison-co.net/elected-offices/chancery-clerk/drupal-search-historical-books/?type=will&method=bookpage")
        
        # Deeds
        # driver.get("https://tools.madison-co.net/elected-offices/chancery-clerk/drupal-search-historical-books/?type=deed&method=bookpage")
        
        # Wait for page to load completely
        time.sleep(5)
        
        # Find the book dropdown - should be available immediately since we're on the correct page
        print("Finding book dropdown...")
        book_dropdown = driver.find_element(By.ID, "book")
        book_select = Select(book_dropdown)
        print("Found book dropdown")
        
        # Build list of target books
        target_books = []
        for option in book_select.options:
            book_text = option.text.strip()
            # Skip placeholder options
            if book_text == "Select Book" or book_text == "":
                continue
                
            # Include "YYY" and any numeric books
            if book_text == "YYY" or (book_text.isdigit() and int(book_text) >= 1):
                target_books.append(book_text)
        
        print(f"Found {len(target_books)} target books")
        
        # Data collection
        all_data = []
        
        # Process each book
        for book_index, book in enumerate(target_books):
            print(f"Processing book {book_index+1}/{len(target_books)}: {book}")
            
            # Select the book
            book_select.select_by_visible_text(book)
            time.sleep(3)  # Allow time for page dropdown to update
            
            # Get page dropdown
            try:
                page_dropdown = driver.find_element(By.ID, "page")
                page_select = Select(page_dropdown)
                
                # Get all valid pages
                page_count = 0
                for page_option in page_select.options:
                    page_text = page_option.text.strip()
                    if page_text == "Select Page" or page_text == "":
                        continue
                    
                    all_data.append({"book": book, "page": page_text})
                    page_count += 1
                
                print(f"  - Added {page_count} pages for book {book}")
                
                # Checkpoint save every 5 books in case of later failure
                if (book_index + 1) % 5 == 0:
                    checkpoint_df = pd.DataFrame(all_data)
                    checkpoint_df.to_excel(f"madison_checkpoint_{book_index+1}.xlsx", index=False)
                    print(f"  - Saved checkpoint at book {book_index+1}")
                
            except Exception as page_error:
                print(f"  - Error processing pages for book {book}: {str(page_error)}")
                continue
        
        # Create final DataFrame and save to Excel
        df = pd.DataFrame(all_data)
        output_file = "madison_county_data.xlsx"
        df.to_excel(output_file, index=False)
        print(f"Successfully saved {len(all_data)} book/page combinations to {output_file}")
        
    except Exception as e:
        print(f"ERROR: {str(e)}")
        
        # Save whatever data we have so far
        if all_data and len(all_data) > 0:
            recovery_df = pd.DataFrame(all_data)
            recovery_df.to_excel("madison_recovery_data.xlsx", index=False)
            print(f"Saved {len(all_data)} records to recovery file")
        
    finally:
        driver.quit()

if __name__ == "__main__":
    scrape_madison_county()
