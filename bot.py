import os
import asyncio
import random
import time
import requests
import logging
import threading
from datetime import datetime, timedelta
from typing import List, Set

from telegram import Update, Message
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, Application
from playwright.async_api import async_playwright, Browser, Page, BrowserContext
from playwright_stealth import stealth_async

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
    # Windows Desktop
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/122.0.0.0",
    # Mac Desktop
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3.1 Safari/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:123.0) Gecko/20100101 Firefox/123.0",
    # Linux Desktop
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:123.0) Gecko/20100101 Firefox/123.0",
    # Android Mobile
    "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.6261.64 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36",
    # iOS Mobile
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_3_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3.1 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPad; CPU OS 17_3_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3.1 Mobile/15E148 Safari/604.1"
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
        self.playwright = None

    async def start_browser(self):
        if not self.playwright:
            self.playwright = await async_playwright().start()
        if not self.browser:
            self.browser = await self.playwright.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-blink-features=AutomationControlled"]
            )

    async def stop_browser(self):
        if self.browser:
            await self.browser.close()
            self.browser = None
        if self.playwright:
            await self.playwright.stop()
            self.playwright = None

    async def generate_usernames(self) -> List[str]:
        # Keep generation logic exactly as requested
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
                    "messages": [{"role": "user", "content": prompt}],
                    "timeout": 30
                }
            )
            data = response.json()
            content = data['choices'][0]['message']['content']
            usernames = [u.strip().lower() for u in content.split(',') if u.strip()]
            new_usernames = [u for u in usernames if u not in self.used_usernames]
            self.used_usernames.update(new_usernames)
            return new_usernames
        except Exception as e:
            logging.error(f"AI Generation Error: {e}")
            return []

    async def check_username(self, username: str) -> bool:
        await self.start_browser()
        
        # Create a fresh context with a random UA
        context = await self.browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            viewport={'width': 1280, 'height': 720}
        )
        page: Page = await context.new_page()
        
        # Apply stealth
        await stealth_async(page)
        
        try:
            # Go to signup page
            await page.goto("https://www.instagram.com/accounts/emailsignup/", wait_until="domcontentloaded", timeout=30000)
            
            # Find username field - using more robust selectors
            username_input = page.locator("input[name='username']")
            await username_input.wait_for(state="visible", timeout=15000)
            
            # Type like a human
            await username_input.click()
            await username_input.fill("") # Clear
            await page.keyboard.type(username, delay=100)
            
            # Trigger validation by clicking away or pressing Tab
            await page.keyboard.press("Tab")
            
            # Wait for validation spinner to disappear or result to appear
            await asyncio.sleep(3) 
            
            # Check for "Taken" indicators
            is_taken = await page.locator("span[aria-label='Another account is using the same username.']").is_visible()
            if not is_taken:
                # Check for X icon which often appears for taken names
                is_taken = await page.locator("span.coreSpriteInputError").is_visible()

            # Check for "Available" indicators
            is_available = await page.locator("span[aria-label='Username is available']").is_visible()
            if not is_available:
                # Check for checkmark icon
                is_available = await page.locator("span.coreSpriteInputAccepted").is_visible()

            # If we can't find either, check if the error message is NOT there
            if not is_taken and not is_available:
                # Final check: if no error sprite is visible after 5 seconds, it's likely available or blocked
                # But we'll be conservative to reduce false positives
                pass

            await context.close()
            return is_available
            
        except Exception as e:
            logging.error(f"Check Error for {username}: {e}")
            await context.close()
            raise e

    def get_status_text(self):
        return (
            "🔍 Searching usernames...\n\n"
            f"📊 Attempts: {self.attempts}\n"
            f"✅ Available: {self.available_count}\n"
            f"❌ Taken: {self.taken_count}\n"
            f"✨ Current: `{self.current_username}`"
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
    
    finder.status_message = await update.message.reply_text(finder.get_status_text(), parse_mode='Markdown')
    
    # Start the loop in the background
    asyncio.create_task(run_loop(update, context))

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    finder.is_running = False
    await update.message.reply_text("🛑 Username search stopped.")
    await finder.stop_browser()

async def run_loop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    while finder.is_running:
        try:
            usernames = await finder.generate_usernames()
            if not usernames:
                error_msg = await update.message.reply_text("⚠️ Failed to generate usernames. Retrying in 10s...")
                asyncio.create_task(delete_message_after(error_msg, 10))
                await asyncio.sleep(10)
                continue

            for username in usernames:
                if not finder.is_running:
                    break
                
                finder.current_username = username
                finder.attempts += 1
                
                # Update status message
                try:
                    await finder.status_message.edit_text(finder.get_status_text(), parse_mode='Markdown')
                except:
                    # If status message was deleted, recreate it
                    finder.status_message = await update.message.reply_text(finder.get_status_text(), parse_mode='Markdown')

                try:
                    is_available = await finder.check_username(username)
                    
                    if is_available:
                        finder.available_count += 1
                        found_msg = await update.message.reply_text(
                            f"🎉 **AVAILABLE USERNAME FOUND**\n\n`{username}`",
                            parse_mode='Markdown'
                        )
                        # Auto-delete after 2 minutes
                        asyncio.create_task(delete_message_after(found_msg, 120))
                    else:
                        finder.taken_count += 1
                
                except Exception as e:
                    error_msg = await update.message.reply_text(f"❌ Error checking {username}: {str(e)[:100]}")
                    asyncio.create_task(delete_message_after(error_msg, 10))
                    # Restart browser on error to clear state
                    await finder.stop_browser()
                    await asyncio.sleep(5)
                    break 

                # Random delay to prevent rate limits
                await asyncio.sleep(random.uniform(1.5, 4.0))

        except Exception as e:
            logging.error(f"Loop Error: {e}")
            await asyncio.sleep(10)

async def main():
    if not TELEGRAM_BOT_TOKEN or not OPENROUTER_API_KEY:
        print("Error: TELEGRAM_BOT_TOKEN and OPENROUTER_API_KEY must be set.")
        return

    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("ig", ig_command))
    application.add_handler(CommandHandler("stop", stop_command))
    
    print("Bot is starting...")
    
    # Use the proper async startup for v20+ to avoid loop issues
    async with application:
        await application.initialize()
        await application.start()
        await application.updater.start_polling()
        
        # Keep the bot running
        stop_event = asyncio.Event()
        await stop_event.wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
