import os
import asyncio
import random
import time
import requests
import logging
from datetime import datetime, timedelta
from typing import List, Set

from telegram import Update, Message
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from playwright.async_api import async_playwright, Browser, Page

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Environment Variables
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

# Constants
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/119.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Mobile/15E148 Safari/604.1"
]

class UsernameFinder:
    def __init__(self):
        self.is_running = False
        self.attempts = 0
        self.available_count = 0
        self.taken_count = 0
        self.current_username = ""
        self.status_message: Message = None
        self.used_usernames: Set[str] = set()
        self.browser: Browser = None
        self.context = None

    async def start_browser(self):
        playwright = await async_playwright().start()
        self.browser = await playwright.chromium.launch(headless=True)
        self.context = await self.browser.new_context(user_agent=random.choice(USER_AGENTS))

    async def stop_browser(self):
        if self.browser:
            await self.browser.close()

    async def generate_usernames(self) -> List[str]:
        prompt = """Generate 20 unique, readable Instagram usernames in the following styles:
1. TECH STYLE (for 'aadi'): Examples: aadi.js, aadi.py, aadi.dev, aadi.stack.
2. NATURE STYLE: Examples: earth.drift, river.slow, storm.wild, ocean.chill.
3. SARCASTIC STYLE: Examples: nothing.special, barely.awake, too.lazy. (Max length 12 chars).

Rules:
- Readable, no random strings.
- No duplicates.
- Return ONLY a comma-separated list of usernames. No other text."""

        try:
            response = requests.post(
                url="https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "nvidia/nemotron-3-super:free",
                    "messages": [{"role": "user", "content": prompt}]
                }
            )
            data = response.json()
            content = data['choices'][0]['message']['content']
            usernames = [u.strip().lower() for u in content.split(',') if u.strip()]
            # Filter out already used ones
            new_usernames = [u for u in usernames if u not in self.used_usernames]
            self.used_usernames.update(new_usernames)
            return new_usernames
        except Exception as e:
            logging.error(f"AI Generation Error: {e}")
            return []

    async def check_username(self, username: str) -> bool:
        if not self.browser:
            await self.start_browser()
        
        page: Page = await self.context.new_page()
        try:
            # Rotate User Agent for each check
            await self.context.set_extra_http_headers({"User-Agent": random.choice(USER_AGENTS)})
            
            await page.goto("https://www.instagram.com/accounts/emailsignup/", wait_until="networkidle")
            
            # Find username field
            username_input = page.locator("input[name='username']")
            await username_input.wait_for(state="visible", timeout=10000)
            await username_input.fill(username)
            
            # Wait for validation (Instagram usually shows a checkmark or X)
            # We check for the error message or the success icon
            await asyncio.sleep(2) # Wait for debounce
            
            # If an error message appears, it's taken
            error_locator = page.locator("span[aria-label='Another account is using the same username.']")
            is_taken = await error_locator.is_visible()
            
            # Also check for success icon (aria-label="Username is available")
            success_locator = page.locator("span[aria-label='Username is available']")
            is_available = await success_locator.is_visible()
            
            await page.close()
            
            if is_available:
                return True
            if is_taken:
                return False
            
            # Fallback: if neither is clear, assume taken to be safe or retry
            return False
            
        except Exception as e:
            logging.error(f"Check Error for {username}: {e}")
            await page.close()
            raise e

    def get_status_text(self):
        return (
            "Searching usernames...\n\n"
            f"Attempts: {self.attempts}\n"
            f"Available: {self.available_count}\n"
            f"Taken: {self.taken_count}\n"
            f"Current username: {self.current_username}"
        )

finder = UsernameFinder()

async def delete_message_after(message: Message, delay: int):
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except:
        pass

async def ig_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if finder.is_running:
        await update.message.reply_text("Finder is already running!")
        return

    finder.is_running = True
    finder.attempts = 0
    finder.available_count = 0
    finder.taken_count = 0
    
    finder.status_message = await update.message.reply_text(finder.get_status_text())
    
    asyncio.create_task(run_loop(update, context))

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    finder.is_running = False
    await update.message.reply_text("Username search stopped.")
    if finder.browser:
        await finder.stop_browser()

async def run_loop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    while finder.is_running:
        try:
            usernames = await finder.generate_usernames()
            if not usernames:
                error_msg = await update.message.reply_text("Failed to generate usernames. Retrying...")
                asyncio.create_task(delete_message_after(error_msg, 10))
                await asyncio.sleep(5)
                continue

            for username in usernames:
                if not finder.is_running:
                    break
                
                finder.current_username = username
                finder.attempts += 1
                
                # Update status message
                try:
                    await finder.status_message.edit_text(finder.get_status_text())
                except:
                    pass

                try:
                    is_available = await finder.check_username(username)
                    
                    if is_available:
                        finder.available_count += 1
                        found_msg = await update.message.reply_text(
                            f"✅ AVAILABLE USERNAME FOUND\n\n`{username}`",
                            parse_mode='Markdown'
                        )
                        asyncio.create_task(delete_message_after(found_msg, 120)) # 2 minutes
                    else:
                        finder.taken_count += 1
                
                except Exception as e:
                    error_msg = await update.message.reply_text(f"Error checking {username}: {str(e)[:100]}")
                    asyncio.create_task(delete_message_after(error_msg, 10))
                    # Restart browser on error
                    await finder.stop_browser()
                    await asyncio.sleep(5)
                    break # Break inner loop to regenerate/restart

                # Random delay to prevent rate limits
                await asyncio.sleep(random.uniform(1.5, 4.0))

        except Exception as e:
            logging.error(f"Loop Error: {e}")
            await asyncio.sleep(10)

if __name__ == "__main__":
    if not TELEGRAM_BOT_TOKEN or not OPENROUTER_API_KEY:
        print("Error: TELEGRAM_BOT_TOKEN and OPENROUTER_API_KEY must be set.")
        exit(1)

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("ig", ig_command))
    app.add_handler(CommandHandler("stop", stop_command))
    
    print("Bot is starting...")
    app.run_polling()
