# pyright: strict

import os
import asyncio
import json
from typing import List, Callable, Union, Awaitable, Optional
from datetime import datetime
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

# Handle dotenv import more gracefully
try:
    # Try to import python-dotenv
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()  # Load environment variables from .env file
    print("Loaded environment variables from .env file")
except ImportError:
    def load_dotenv() -> None:
        pass
    load_dotenv()

from emailer import Email

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Set more verbose logging for the python-telegram-bot library
telegram_logger = logging.getLogger('telegram')
telegram_logger.setLevel(logging.INFO)
ptb_logger = logging.getLogger('telegram.ext')
ptb_logger.setLevel(logging.DEBUG)

# Even more specific control - filter out the Bot's enter/exit debug messages
bot_logger = logging.getLogger('telegram.Bot')
bot_logger.setLevel(logging.WARNING)

class TelegramBot:
    def __init__(
        self,
        token: str,
        chat_id: str,
        admin_ids: List[str] = None,
    ):
        """
        Initialize the Telegram bot.

        Args:
            token: The Telegram bot token obtained from BotFather
            chat_id: The default chat ID to send messages to
            admin_ids: List of admin user IDs that are allowed to interact with the bot
        """
        self.token = token
        self.chat_id = chat_id
        self.admin_ids = admin_ids or []

        # Store the allowed update types to use when polling starts
        self.allowed_updates = ["callback_query", "message"]

        # Initialize the update offset for polling
        self._offset = 0
        self._polling_task = None

        # Configure the application with defaults for v20+
        builder = Application.builder()
        builder.token(token)
        # Don't use a persistence instance by default
        builder.persistence(None)
        # Set up with concurrent updates
        builder.concurrent_updates(True)

        # Build the application
        self.application = builder.build()

        # Store a direct reference to the bot for manual polling
        try:
            # This works in all python-telegram-bot versions
            self.bot = Bot(token=token)
            logger.info("Created direct Bot instance for manual polling")
        except Exception as e:
            logger.warning(f"Could not create direct Bot instance: {e}")
            # Fall back to the application's bot
            self.bot = self.application.bot

        self.pending_actions = {}  # Store pending actions with message_id as key
        self._setup_handlers()

    def _setup_handlers(self):
        """Set up the command and callback handlers for the bot."""
        self.application.add_handler(CommandHandler("start", self._start_command))
        self.application.add_handler(CommandHandler("test", self._test_command))
        self.application.add_handler(CallbackQueryHandler(self._button_callback))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._message_handler))

    async def _start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle the /start command."""
        user_id = str(update.effective_user.id)
        if user_id in self.admin_ids or not self.admin_ids:
            await update.message.reply_text("Hello! I'm your friendly support assistant. I'll notify you about new support emails.")
        else:
            await update.message.reply_text("You're not authorized to use this bot.")

    async def _test_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle the /test command to verify the bot is functioning."""
        user_id = str(update.effective_user.id)
        if user_id in self.admin_ids or not self.admin_ids:
            # Create test inline keyboard
            keyboard = [
                [
                    InlineKeyboardButton("Test Button", callback_data=json.dumps({"action": "test", "value": "clicked"}))
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(
                "Bot is functioning properly! Click the button below to test callbacks.",
                reply_markup=reply_markup
            )
        else:
            await update.message.reply_text("You're not authorized to use this command.")

    async def _message_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle text messages."""
        user_id = str(update.effective_user.id)
        if user_id in self.admin_ids or not self.admin_ids:
            await update.message.reply_text("I only respond to email notifications. Please wait for new support emails.")

    async def _button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle button callbacks for send/draft actions."""
        query = update.callback_query
        logger.info(f"Received callback query from user {query.from_user.id} with data: {query.data}")
        await query.answer()

        # Extract the action and email ID from the callback data
        try:
            data = json.loads(query.data)
            action = data.get("action")
            logger.info(f"Parsed callback data: action={action}")

            # Handle test button clicks
            if action == "test":
                logger.info("Processing test button callback")
                await query.edit_message_text(
                    text="✅ Button clicked successfully! The callback system is working.",
                    reply_markup=None
                )
                return

            # Handle email actions
            email_id = data.get("email_id")
            logger.info(f"Processing email action: {action} for email_id: {email_id}")

            if email_id in self.pending_actions:
                logger.info(f"Found pending action for email_id: {email_id}")
                email_thread = self.pending_actions[email_id]["email_thread"]
                draft_email = self.pending_actions[email_id]["draft_email"]

                # Get the original message content
                most_recent = email_thread[-1]

                # Helper function to clean HTML and limit text
                def clean_text(text: str, max_length: int = 300) -> str:
                    # Remove HTML tags
                    import re
                    clean = re.sub(r'<[^>]*>', '', text)
                    # Limit length and add ellipsis if needed
                    if len(clean) > max_length:
                        return clean[:max_length] + "..."
                    return clean

                # Get clean versions of email body text
                email_body_clean = clean_text(most_recent.body, 300)
                draft_body_clean = clean_text(draft_email.body, 500)

                # Format the original message part
                original_message = (
                    f"📧 <b>Support Email</b>\n\n"
                    f"<b>From:</b> {most_recent.from_address}\n"
                    f"<b>Subject:</b> {most_recent.subject}\n\n"
                    f"<b>Message:</b>\n{email_body_clean}\n\n"
                    f"<b>Draft Response:</b>\n{draft_body_clean}\n\n"
                )

                if action == "send":
                    logger.info(f"User chose to send the email to {draft_email.to_address}")
                    # Append confirmation to original message
                    await query.edit_message_text(
                        text=f"{original_message}<b>✅ Email will be sent!</b>",
                        reply_markup=None,
                        parse_mode="HTML"
                    )
                    # Return the draft email for sending
                    self.pending_actions[email_id]["result"] = draft_email
                    self.pending_actions[email_id]["event"].set()
                    logger.info(f"Set event for email_id: {email_id} with action: send")

                elif action == "draft":
                    logger.info(f"User chose to save email as draft")
                    # Append confirmation to original message
                    await query.edit_message_text(
                        text=f"{original_message}<b>📝 Email saved as draft!</b>",
                        reply_markup=None,
                        parse_mode="HTML"
                    )
                    # Return None to indicate save as draft
                    self.pending_actions[email_id]["result"] = None
                    self.pending_actions[email_id]["event"].set()
                    logger.info(f"Set event for email_id: {email_id} with action: draft")
            else:
                logger.warning(f"No pending action found for email_id: {email_id}")
                await query.edit_message_text(
                    text="⚠️ This action has expired or is no longer valid.",
                    reply_markup=None
                )

        except Exception as e:
            logger.error(f"Error processing callback: {e}", exc_info=True)
            await query.edit_message_text(text=f"Error: {str(e)}")

    async def notify_and_wait_for_action(self, email_thread: List[Email], draft_email: Email) -> Union[Email, None]:
        """
        Send notification to Telegram about new email and wait for action.

        Args:
            email_thread: List of emails in the thread
            draft_email: Draft email response

        Returns:
            The draft email if "send" action is chosen, None if "draft" action is chosen
        """
        if not email_thread:
            logger.warning("No email thread provided to notify_and_wait_for_action")
            return None

        most_recent = email_thread[-1]
        logger.info(f"Processing notification for email from {most_recent.from_address} with subject: {most_recent.subject}")

        # Create a unique ID for this action
        unique_id = most_recent.id or str(datetime.now().timestamp())
        logger.debug(f"Generated unique_id for action: {unique_id}")

        # Helper function to clean HTML and limit text
        def clean_text(text: str, max_length: int = 300) -> str:
            # Remove HTML tags
            import re
            clean = re.sub(r'<[^>]*>', '', text)
            # Limit length and add ellipsis if needed
            if len(clean) > max_length:
                return clean[:max_length] + "..."
            return clean

        # Get clean versions of email body text
        email_body_clean = clean_text(most_recent.body, 300)
        draft_body_clean = clean_text(draft_email.body, 500)

        # Format the message with email details and draft response
        message = (
            f"📧 <b>New Support Email</b>\n\n"
            f"<b>From:</b> {most_recent.from_address}\n"
            f"<b>Subject:</b> {most_recent.subject}\n\n"
            f"<b>Message:</b>\n{email_body_clean}\n\n"
            f"<b>Draft Response:</b>\n{draft_body_clean}\n\n"
            f"What would you like to do with this draft?"
        )

        # Create inline keyboard with send and draft buttons
        keyboard = [
            [
                InlineKeyboardButton("Send Response", callback_data=json.dumps({"action": "send", "email_id": unique_id})),
                InlineKeyboardButton("Save as Draft", callback_data=json.dumps({"action": "draft", "email_id": unique_id}))
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        logger.info(f"Sending notification to Telegram chat {self.chat_id}")
        logger.debug(f"Callback data for Send: {json.dumps({'action': 'send', 'email_id': unique_id})}")
        logger.debug(f"Callback data for Draft: {json.dumps({'action': 'draft', 'email_id': unique_id})}")

        # Send the message and get the message object
        try:
            sent_message = await self.application.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                reply_markup=reply_markup,
                parse_mode="HTML"
            )
            logger.info(f"Successfully sent notification message to Telegram (ID: {sent_message.message_id})")
        except Exception as e:
            logger.error(f"Error sending HTML message: {e}")
            # Fallback to plain text if HTML parsing fails
            message_plain = (
                f"📧 New Support Email\n\n"
                f"From: {most_recent.from_address}\n"
                f"Subject: {most_recent.subject}\n\n"
                f"Message:\n{email_body_clean}\n\n"
                f"Draft Response:\n{draft_body_clean}\n\n"
                f"What would you like to do with this draft?"
            )
            logger.info("Retrying with plain text message")
            sent_message = await self.application.bot.send_message(
                chat_id=self.chat_id,
                text=message_plain,
                reply_markup=reply_markup
            )
            logger.info(f"Successfully sent plain text notification to Telegram (ID: {sent_message.message_id})")

        # Create an event to wait for the callback
        event = asyncio.Event()

        # Store the pending action
        self.pending_actions[unique_id] = {
            "email_thread": email_thread,
            "draft_email": draft_email,
            "event": event,
            "result": None
        }
        logger.info(f"Registered action with ID {unique_id}, waiting for response")

        # Wait for the event to be set (when the user clicks a button)
        try:
            logger.info(f"Waiting for user response (timeout: 3600s)")
            await asyncio.wait_for(event.wait(), timeout=3600)  # 1 hour timeout
            result = self.pending_actions[unique_id]["result"]
            del self.pending_actions[unique_id]
            logger.info(f"Received user response: {'send email' if result else 'save as draft'}")
            return result
        except asyncio.TimeoutError:
            # If no action is taken within the timeout, remove the buttons
            logger.warning(f"Timeout waiting for user response, removing buttons")
            await self.application.bot.edit_message_reply_markup(
                chat_id=self.chat_id,
                message_id=sent_message.message_id,
                reply_markup=None
            )
            del self.pending_actions[unique_id]
            logger.info("Action timed out, returning None (save as draft)")
            return None

    async def start(self):
        """Start the Telegram bot."""
        try:
            logger.info("Starting Telegram bot...")

            # Initialize the application
            await self.application.initialize()

            # Start the application (bot framework)
            await self.application.start()

            # Start polling in a separate task
            self._polling_task = asyncio.create_task(self._start_polling())

            # Send a startup message
            await self.application.bot.send_message(
                chat_id=self.chat_id,
                text="🤖 Friendly support bot is now online and ready to process emails."
            )
            logger.info("Telegram bot started successfully")
        except Exception as e:
            logger.error(f"Error starting Telegram bot: {e}", exc_info=True)
            raise

    async def _start_polling(self):
        """Start polling for updates in the background."""
        try:
            logger.info("Starting background polling task")

            # Log the current state
            logger.info(f"Initial offset: {self._offset}")
            logger.info(f"Allowed updates: {self.allowed_updates}")

            # Use direct polling
            while True:
                try:
                    logger.debug("Requesting updates from Telegram...")
                    # Get updates every 1 second from our direct bot instance
                    updates = await self.bot.get_updates(
                        offset=self._offset,
                        timeout=1,
                        allowed_updates=self.allowed_updates
                    )

                    logger.debug(f"Received {len(updates)} updates")

                    # Process updates
                    for update in updates:
                        # Update offset to acknowledge this update
                        self._offset = update.update_id + 1

                        # Log detailed information about the update
                        update_type = "unknown"
                        if hasattr(update, "callback_query") and update.callback_query:
                            update_type = "callback_query"
                            callback_data = getattr(update.callback_query, "data", "unknown")
                            logger.info(f"Received callback query with data: {callback_data}")
                        elif hasattr(update, "message") and update.message:
                            update_type = "message"
                            if hasattr(update.message, "text"):
                                logger.info(f"Received message: {update.message.text}")
                            else:
                                logger.info("Received message without text")

                        logger.info(f"Received update ID: {update.update_id}, type: {update_type}")

                        # Process using our direct handler
                        await self.process_update(update)

                    # Small delay to prevent tight loop
                    await asyncio.sleep(0.1)
                except Exception as e:
                    logger.error(f"Error in polling loop: {e}", exc_info=True)
                    await asyncio.sleep(1)  # Wait a bit before retrying
        except asyncio.CancelledError:
            logger.info("Polling task was cancelled")
        except Exception as e:
            logger.error(f"Polling task encountered an error: {e}", exc_info=True)

    async def stop(self):
        """Stop the Telegram bot."""
        try:
            logger.info("Stopping Telegram bot...")

            # Cancel polling task if it exists
            if self._polling_task and not self._polling_task.done():
                logger.info("Cancelling polling task...")
                self._polling_task.cancel()
                try:
                    await self._polling_task
                except asyncio.CancelledError:
                    logger.info("Polling task cancelled successfully")

            # Graceful shutdown
            try:
                # Stop the application
                await self.application.stop()
                await self.application.shutdown()
                logger.info("Application shutdown successfully")
            except Exception as e:
                logger.warning(f"Error during application shutdown: {e}")

            logger.info("Telegram bot stopped successfully")
        except Exception as e:
            logger.error(f"Error stopping Telegram bot: {e}", exc_info=True)

    @classmethod
    def from_env(cls):
        """Create a TelegramBot instance from environment variables."""
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not token:
            raise ValueError("TELEGRAM_BOT_TOKEN environment variable is not set")

        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        if not chat_id:
            raise ValueError("TELEGRAM_CHAT_ID environment variable is not set")

        admin_ids_str = os.getenv("TELEGRAM_ADMIN_IDS", "")
        admin_ids = admin_ids_str.split(",") if admin_ids_str else []

        logger.info(f"Creating Telegram bot with chat_id: {chat_id}")
        if admin_ids:
            logger.info(f"Admin IDs configured: {', '.join(admin_ids)}")
        else:
            logger.info("No admin IDs configured, anyone can interact with the bot")

        # Verify that the python-telegram-bot version is compatible
        try:
            import telegram
            version = telegram.__version__
            logger.info(f"Using python-telegram-bot version {version}")
        except (ImportError, AttributeError):
            logger.warning("Could not detect python-telegram-bot version")

        return cls(token=token, chat_id=chat_id, admin_ids=admin_ids)

    async def process_update(self, update):
        """Process a single update using our handlers directly."""
        try:
            logger.debug(f"Processing update directly: {update.update_id}")

            # Handle callback queries
            if hasattr(update, "callback_query") and update.callback_query:
                logger.info("Handling callback query directly")
                await self._button_callback(update, None)
                return

            # Handle messages
            if hasattr(update, "message") and update.message:
                logger.info("Handling message directly")

                # Check if it's a command
                if hasattr(update.message, "text"):
                    text = update.message.text
                    if text.startswith('/start'):
                        await self._start_command(update, None)
                        return
                    elif text.startswith('/test'):
                        await self._test_command(update, None)
                        return

                # Otherwise treat as regular message
                await self._message_handler(update, None)
                return

            logger.warning(f"Received update of unknown type: {update}")
        except Exception as e:
            logger.error(f"Error in direct update processing: {e}", exc_info=True)
