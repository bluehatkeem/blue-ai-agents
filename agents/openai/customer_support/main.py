import env
import asyncio
from emailer import Emailer, Email
from telegram_bot import TelegramBot
from typing import Union, List, Callable, Awaitable
import support_agent
import markdown as markdown
import json
import os
import socket
import imaplib
import time
import datetime
import email
import re
import smtplib
from email.header import decode_header, make_header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, make_msgid

from agents import (
    ItemHelpers,
    TResponseInputItem,
)


env.ensure("STRIPE_SECRET_KEY")
env.ensure("OPENAI_API_KEY")

email_address = env.ensure("EMAIL_ADDRESS")
support_address = env.get_or("SUPPORT_ADDRESS", email_address)
email_password = env.ensure("EMAIL_PASSWORD")

# Get SMTP server settings from environment variables
smtp_server = os.getenv("SMTP_SERVER")
smtp_port = int(os.getenv("SMTP_PORT", "587")) if os.getenv("SMTP_PORT") else None

# Get SMTP authentication credentials - use separate credentials if provided
smtp_username = os.getenv("SMTP_USERNAME", email_address)  # Default to email_address if not provided
smtp_password = os.getenv("SMTP_PASSWORD", email_password)  # Default to email_password if not provided

# Print SMTP configuration for debugging
print("\n=== SMTP Configuration ===")
print(f"SMTP Server: {smtp_server}")
print(f"SMTP Port: {smtp_port}")
print(f"SMTP Username: {smtp_username}")
print(f"SMTP Password: {'*' * len(smtp_password) if smtp_password else 'None'}")

# Try to resolve the SMTP server hostname
if smtp_server:
    try:
        print(f"Resolving {smtp_server}...")
        ip_address = socket.gethostbyname(smtp_server)
        print(f"Resolved {smtp_server} to {ip_address}")
    except socket.gaierror as e:
        print(f"WARNING: Could not resolve {smtp_server}: {e}")
print("===========================\n")

# Initialize the emailer with SMTP settings from environment variables
emailer = Emailer(
    email_address=email_address,
    email_password=email_password,
    support_address=support_address,
    smtp_server=smtp_server,
    smtp_port=smtp_port,
    smtp_username=smtp_username,
    smtp_password=smtp_password
)

# Initialize Telegram bot if environment variables are set
telegram_bot = None
try:
    telegram_bot = TelegramBot.from_env()
    print("\n=== Telegram Bot Configuration ===")
    print("Telegram Bot initialized successfully")
    print("===========================\n")
except ValueError as e:
    print(f"\n=== Telegram Bot Configuration ===")
    print(f"Telegram Bot initialization failed: {e}")
    print(f"Telegram notifications will be disabled")
    print("===========================\n")

# Add a global set to track processed email IDs
processed_email_ids = set()

# Replace with a more sophisticated tracking system
# Format: {email_id: {'thread_length': length, 'timestamp': time}}
processed_threads = {}

active_tasks = {}  # { email_id: asyncio.Task }

def unsure(str: str) -> bool:
    return (
        "not sure" in str
        or "unsure" in str
        or "don't know" in str
        or "dont know" in str
        or "do not know" in str
    )


async def respond(thread: List[Email]) -> Union[Email, None]:
    most_recent = thread[-1]
    print(f"Got unread email:\n  {json.dumps(most_recent.to_dict())}")

    # Loop through the entire thread to add historical context for the agent
    input_items: list[TResponseInputItem] = []
    for email in thread:
        input_items.append(
            {
                "content": (
                    "This is an earlier email:"
                    f"Email from: {email.from_address}\n"
                    f"To: {email.to_address}\n"
                    f"Subject: {email.subject}\n\n"
                    f"{email.body}"
                ),
                "role": "user",
            }
        )

    input_items.append(
        {
            "content": (
                "This the latest email"
                "You can use context from earlier emails"
                "but reply specifically to the following email:"
                f"Email from: {most_recent.from_address}\n"
                f"To: {most_recent.to_address}\n"
                f"Subject: {most_recent.subject}\n\n"
                f"{most_recent.body}"
            ),
            "role": "user",
        }
    )

    print(f"Sending to agent:\n  {json.dumps(input_items)}")

    output = await support_agent.run(input_items)
    body_md = ItemHelpers.text_message_outputs(output.new_items)

    # Handle answers that the agent doesn't know
    if unsure(body_md.lower()):
        print(
            f"Agent doesn't know, ignore response and keep email in the inbox:\n{body_md}"
        )
        return None

    # OpenAI often returns the body in html fences, trim those
    body_html = markdown.markdown(body_md, extensions=["tables"])

    # Create draft email response
    draft_email = Email(
        from_address=most_recent.to_address,
        to_address=most_recent.from_address,
        subject=most_recent.subject,
        body=body_html,
    )

    print(f"DEBUG: telegram_bot is {'available' if telegram_bot else 'None'}")

    # If Telegram bot is available, send notification and wait for action
    if telegram_bot:
        try:
            print("Sending notification to Telegram and waiting for approval...")
            print(f"DEBUG: thread length: {len(thread)}, most recent subject: {most_recent.subject}")
            print(f"DEBUG: draft_email subject: {draft_email.subject}, length: {len(draft_email.body)}")

            result = await telegram_bot.notify_and_wait_for_action(thread, draft_email)
            print(f"DEBUG: Received result from notify_and_wait_for_action: {result is not None}")

            if result is not None:
                print("Telegram user approved sending the email")
                return result
            else:
                print("Telegram user chose to save as draft or timeout occurred")
                # Create a draft email in Gmail
                await save_draft(draft_email, most_recent)
                # Return a special marker object indicating we created a draft and should keep as unread
                draft_marker = Email(
                    from_address="DRAFT_MARKER",
                    to_address="DRAFT_MARKER",
                    subject="DRAFT_MARKER",
                    body="DRAFT_MARKER"
                )
                draft_marker.id = "DRAFT_MARKER"
                return draft_marker

        except Exception as e:
            print(f"Error sending Telegram notification: {str(e)}")
            import traceback
            traceback.print_exc()
            # Fall back to sending email directly if Telegram fails
            print("Falling back to sending email directly without Telegram notification")
            return draft_email
    else:
        # No Telegram bot available, return draft email for sending
        print("DEBUG: No Telegram bot available, sending email directly")
        return draft_email


async def save_draft(draft_email: Email, original_email: Email):
    """Save the draft email in Gmail without sending it."""
    try:
        print(f"Saving draft for email from {original_email.from_address} with subject: {original_email.subject}")

        # Create the email message
        message = draft_email.to_message(original_email.message_id)

        # Convert the message to a string
        email_str = message.as_string()

        # Connect to IMAP
        imap_conn = emailer._ensure_imap_connection()

        # Select the drafts folder (for Gmail it's typically "[Gmail]/Drafts")
        drafts_folder = '"[Gmail]/Drafts"'  # Default drafts folder
        try:
            # Try standard Gmail draft folder
            result, data = imap_conn.select(drafts_folder)
            if result != 'OK':
                # Try alternative names for the drafts folder
                drafts_folder = '"Drafts"'
                result, data = imap_conn.select(drafts_folder)
                if result != 'OK':
                    drafts_folder = '"[Google Mail]/Drafts"'
                    result, data = imap_conn.select(drafts_folder)
                    if result != 'OK':
                        print("Could not find Drafts folder, using INBOX instead")
                        drafts_folder = 'INBOX'
                        imap_conn.select(drafts_folder)
        except Exception as e:
            print(f"Error selecting drafts folder: {e}, using INBOX instead")
            drafts_folder = 'INBOX'
            imap_conn.select(drafts_folder)

        # Append the message to the drafts folder
        # The first parameter should be the mailbox name, not imap_conn.SELECTED
        result, data = imap_conn.append(
            drafts_folder,  # Use the actual mailbox name
            '\\Draft',
            imaplib.Time2Internaldate(time.time()),
            email_str.encode('utf-8')
        )

        if result == 'OK':
            print(f"Draft saved successfully to {drafts_folder}")
        else:
            print(f"Failed to save draft: {result} - {data}")

    except Exception as e:
        print(f"Error saving draft: {e}")
        import traceback
        traceback.print_exc()


async def handle_thread(emailer, respond, imap_conn, email_thread):
    global active_tasks
    most_recent = email_thread[-1]
    email_id = most_recent.id

    try:
        # Generate the response (this calls notify_and_wait_for_action in the Telegram bot)
        response = await respond(email_thread)
        if response is None or response.id == "DRAFT_MARKER":
            print(f"[handle_thread] Draft saved. Email {most_recent.id} remains unread.")
        else:
            print(f"[handle_thread] Sending an email response to {response.to_address}...")
            smtp_conn = emailer._connect_to_smtp()
            message = response.to_message(emailer.support_address)
            smtp_conn.send_message(message)
            smtp_conn.quit()

            emailer.mark_as_read(imap_conn, most_recent.id)
            print(f"[handle_thread] Marked email {most_recent.id} as read.")

    except Exception as e:
        print(f"[handle_thread] Error handling thread for email {most_recent.id}: {e}")
    finally:
        # Important: remove from active_tasks so future messages in this thread can spawn new tasks
        active_tasks.pop(email_id, None)
        print(f"[handle_thread] Finished email thread {email_id}, removed task from active_tasks.")


async def process_with_draft_handling(emailer, respond):
    """
    Process emails in parallel, so we don't block on older emails
    while waiting for Telegram responses.
    """
    imap_conn = emailer._ensure_imap_connection()
    unread_threads = emailer._get_unread_emails(imap_conn)

    if not unread_threads:
        print("[process_with_draft_handling] No unread emails found.")
        return

    # For each unread thread, spawn a new task if not already present
    for thread in unread_threads:
        most_recent = thread[-1]
        # Use the unique email ID (or thread ID) as the key
        email_id = most_recent.id

        # If there's already a task for this email, skip
        if email_id in active_tasks:
            continue

        # Create a new task
        t = asyncio.create_task(handle_thread(emailer, respond, imap_conn, thread))
        active_tasks[email_id] = t
        print(f"[process_with_draft_handling] Spawned async task for email ID {email_id}")

    # Do not await tasks here, just let them run in the background


async def main():
    # Declare telegram_bot as global since we're modifying it
    global telegram_bot

    # Initialize or disable the Telegram bot
    telegram_status = "disabled"
    if telegram_bot:
        try:
            # Print status
            print("\n=== Starting Telegram Bot ===")
            print("Attempting to start Telegram bot...")

            # Start the Telegram bot
            await telegram_bot.start()

            # Send a direct test message to verify connectivity
            try:
                await telegram_bot.application.bot.send_message(
                    chat_id=telegram_bot.chat_id,
                    text="🔄 System test message: The email monitoring system has been started. This message confirms that Telegram notifications are working."
                )
                print("✅ Test message sent successfully to Telegram")
            except Exception as e:
                print(f"⚠️ Warning: Could not send test message, but the bot is still running: {str(e)}")

            telegram_status = "enabled"
            print("===========================\n")
        except Exception as e:
            print(f"Error starting Telegram bot: {str(e)}")
            print("Detailed error information:")
            import traceback
            traceback.print_exc()
            print("\nDisabling Telegram functionality due to errors")
            print("===========================\n")
            telegram_bot = None

    try:
        # Run the emailer with our custom process function
        print("Starting email monitoring...")
        while True:
            await process_with_draft_handling(emailer, respond)
            await asyncio.sleep(30)
    except KeyboardInterrupt:
        print("\nKeyboard interrupt received, shutting down gracefully...")
    except Exception as e:
        print(f"\nError in email monitoring: {str(e)}")
        import traceback
        traceback.print_exc()
    finally:
        # Stop the Telegram bot when the emailer stops
        if telegram_bot and telegram_status == "enabled":
            try:
                print("\n=== Stopping Telegram Bot ===")
                print("Shutting down Telegram bot...")
                await telegram_bot.stop()
                print("Telegram bot stopped successfully")
                print("===========================\n")
            except Exception as e:
                print(f"Error stopping Telegram bot: {str(e)}")
                print("Detailed error information:")
                import traceback
                traceback.print_exc()
                print("===========================\n")


if __name__ == "__main__":
    asyncio.run(main())
