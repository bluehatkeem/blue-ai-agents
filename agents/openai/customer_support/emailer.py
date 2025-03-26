# pyright: strict

import imaplib
import email
import smtplib
import ssl
import socket
from email.mime.text import MIMEText
from email.message import Message
from email.mime.multipart import MIMEMultipart
from email.utils import parseaddr, make_msgid
from typing import List, Tuple, Callable, Union, Awaitable, Optional
import asyncio
import json
import re
from datetime import datetime
from email.utils import parsedate_to_datetime
import os

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


class Email:
    def __init__(
        self,
        from_address: str,
        to_address: str,
        subject: str,
        body: str,
        id: str = "",
        message_id: str = "",
        references: str = "",
        date: datetime = datetime.now(),
    ):
        self.id = id
        self.to_address = to_address
        self.from_address = from_address
        self.subject = subject
        self.body = body
        self.date = date
        self.message_id = message_id  # Store the Message-ID header
        self.references = references  # Store the References header

    def to_message(self, reply_to: str) -> MIMEMultipart:
        msg = MIMEMultipart()
        msg["From"] = self.from_address
        msg["To"] = self.to_address

        # Ensure subject has Re: prefix for replies
        if not self.subject.lower().startswith("re:"):
            msg["Subject"] = f"Re: {self.subject}"
        else:
            msg["Subject"] = self.subject

        # Set proper threading headers
        if self.message_id:
            # If we have the original Message-ID, use it for In-Reply-To
            msg["In-Reply-To"] = self.message_id

            # For References, append the original Message-ID to any existing References
            if self.references:
                msg["References"] = f"{self.references} {self.message_id}"
            else:
                msg["References"] = self.message_id

        msg["Reply-To"] = reply_to

        # Add the HTML body
        msg.attach(MIMEText(f"<html><body>{self.body}</body></html>", "html"))
        return msg

    def to_dict(self):
        return {
            "id": self.id,
            "to": self.to_address,
            "from": self.from_address,
            "subject": self.subject,
            "body": self.body,
            "message_id": self.message_id,
            "references": self.references,
            "date": self.date.strftime("%a, %d %b %Y %H:%M:%S %z"),
        }


class Emailer:
    """
    Emailer is an IMAP/SMTP client that can be used to fetch and respond to emails.
    It was mostly vibe-coded so please make improvements!
    TODO: add agent replies to the context
    """

    def __init__(
        self,
        email_address: str,
        email_password: str,
        support_address: str = "",
        imap_server: Optional[str] = None,
        imap_port: Optional[int] = None,
        smtp_server: Optional[str] = None,
        smtp_port: Optional[int] = None,
        smtp_username: Optional[str] = None,
        smtp_password: Optional[str] = None,
    ):
        # Email configuration
        self.email_address = email_address
        self.support_address = support_address if support_address else email_address
        self.email_password = email_password

        # Use environment variables if provided, otherwise use defaults
        self.imap_server = imap_server or os.getenv("IMAP_SERVER") or "imap.gmail.com"
        self.imap_port = imap_port or int(os.getenv("IMAP_PORT", "993"))
        self.smtp_server = smtp_server or os.getenv("SMTP_SERVER") or "smtp.gmail.com"
        self.smtp_port = smtp_port or int(os.getenv("SMTP_PORT", "587"))

        # SMTP authentication credentials
        self.smtp_username = smtp_username or self.email_address
        self.smtp_password = smtp_password or self.email_password

        # Persistent IMAP connection
        self.imap_conn = None

        print("Email configuration initialized with:")
        print(f"  SMTP Server: {self.smtp_server}")
        print(f"  SMTP Port: {self.smtp_port}")
        print(f"  SMTP Username: {self.smtp_username}")
        print(f"  Email Address: {self.email_address}")
        print(f"  Support Address: {self.support_address}")

    def _ensure_imap_connection(self) -> imaplib.IMAP4_SSL:
        """Ensure we have a valid IMAP connection, reconnecting if necessary."""
        try:
            # Check if connection exists and is still alive
            if self.imap_conn is not None:
                try:
                    # NOOP command to check if connection is still alive
                    status, _ = self.imap_conn.noop()
                    if status == 'OK':
                        print("Using existing IMAP connection")
                        return self.imap_conn
                except Exception as e:
                    print(f"Existing IMAP connection is stale: {str(e)}")
                    # Close the stale connection if possible
                    try:
                        self.imap_conn.logout()
                    except:
                        pass
                    self.imap_conn = None

            # Create a new connection
            print(f"Connecting to IMAP server {self.imap_server}:{self.imap_port}...")
            self.imap_conn = imaplib.IMAP4_SSL(self.imap_server, self.imap_port)
            self.imap_conn.login(self.email_address, self.email_password)
            print(f"Successfully logged in to IMAP server as {self.email_address}")

            # Select the INBOX folder
            self.imap_conn.select("INBOX")
            return self.imap_conn

        except Exception as e:
            print(f"Error connecting to IMAP server: {str(e)}")
            self.imap_conn = None
            raise

    def _connect_to_email(self) -> Tuple[imaplib.IMAP4_SSL, Union[smtplib.SMTP_SSL, smtplib.SMTP]]:
        """Establish connections to email servers (both IMAP and SMTP)."""
        # Get IMAP connection
        imap_conn = self._ensure_imap_connection()

        # Connect to SMTP server
        smtp_conn = self._connect_to_smtp()

        return imap_conn, smtp_conn

    def _connect_to_smtp(self) -> Union[smtplib.SMTP_SSL, smtplib.SMTP]:
        """Establish connection to SMTP server only."""
        # Connect to SMTP server with SSL
        print(f"Connecting to SMTP server {self.smtp_server}:{self.smtp_port}...")

        # First, check if we can resolve the hostname
        try:
            print(f"Resolving hostname {self.smtp_server}...")
            socket.gethostbyname(self.smtp_server)
            print(f"Successfully resolved {self.smtp_server}")
        except socket.gaierror as e:
            print(f"WARNING: Could not resolve hostname {self.smtp_server}: {str(e)}")
            raise ConnectionError(f"Could not resolve SMTP server hostname: {self.smtp_server}")

        context = ssl.create_default_context()

        # Set a timeout for SMTP connections - increase from 30 to 60 seconds
        socket.setdefaulttimeout(60)  # 60 seconds timeout

        # For port 587, we should use STARTTLS instead of direct SSL
        if self.smtp_port == 587:
            print("Port 587 detected, using STARTTLS instead of direct SSL...")
            try:
                smtp_conn = smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=60)
                smtp_conn.ehlo()
                smtp_conn.starttls(context=context)
                smtp_conn.ehlo()
                print("Connected to SMTP server using STARTTLS")
            except Exception as e:
                print(f"STARTTLS connection failed: {str(e)}")
                raise ConnectionError(f"Failed to connect to SMTP server using STARTTLS: {str(e)}")
        else:
            # For other ports (like 465), try direct SSL first
            try:
                print(f"Attempting direct SSL connection to {self.smtp_server}:{self.smtp_port}...")
                smtp_conn = smtplib.SMTP_SSL(self.smtp_server, self.smtp_port, context=context, timeout=60)
                print("Connected to SMTP server using direct SSL")
            except Exception as e:
                print(f"Direct SSL connection failed: {str(e)}")
                print("Trying STARTTLS as fallback...")
                try:
                    smtp_conn = smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=60)
                    smtp_conn.ehlo()
                    smtp_conn.starttls(context=context)
                    smtp_conn.ehlo()
                    print("Connected to SMTP server using STARTTLS")
                except Exception as e2:
                    print(f"All SMTP connection attempts failed: {str(e2)}")
                    raise ConnectionError(f"Failed to connect to SMTP server: {str(e2)}")

        # Login to SMTP server with the specific SMTP username and password
        print(f"Logging in to SMTP server as {self.smtp_username}...")
        try:
            smtp_conn.login(self.smtp_username, self.smtp_password)
            print("SMTP login successful!")
        except smtplib.SMTPAuthenticationError as e:
            print(f"SMTP authentication failed: {str(e)}")
            print("Check your SMTP username and password")
            raise smtplib.SMTPAuthenticationError(
                e.smtp_code,
                f"SMTP authentication failed. Check your SMTP username ({self.smtp_username}) and password."
            )

        return smtp_conn

    def _get_body(self, email_message: Message) -> str:
        body: str = ""
        if email_message.is_multipart():
            for part in email_message.walk():
                if part.get_content_type() == "text/plain":
                    payload = part.get_payload(decode=True)
                    if isinstance(payload, bytes):
                        body = payload.decode()
                    break
        else:
            payload = email_message.get_payload(decode=True)
            if isinstance(payload, bytes):
                body = payload.decode()
            else:
                body = str(payload)
        return self._strip_replies(body)

    def _strip_replies(self, raw_body: str) -> str:
        lines = raw_body.split("\n")
        pruned: List[str] = []
        for line in lines:
            # Stop if we see a typical reply indicator
            if line.strip().startswith("On ") and " wrote:" in line:
                break
            pruned.append(line)
        return "\n".join(pruned).strip()

    def _parse_email(
        self, imap_conn: imaplib.IMAP4_SSL, email_id: bytes
    ) -> Union[Email, None]:
        _, msg_data = imap_conn.fetch(email_id.decode(), "(BODY.PEEK[])")
        if not msg_data or not msg_data[0]:
            return None
        msg_resp = msg_data[0]
        if isinstance(msg_resp, tuple) and len(msg_resp) == 2:
            email_body = msg_resp[1]
        else:
            return None

        email_message = email.message_from_bytes(email_body)
        subject = email_message["subject"] or ""
        from_address = parseaddr(email_message.get("From", ""))[1]
        to_address = parseaddr(email_message.get("To", ""))[1]
        date_str = email_message.get("Date", "")
        date = datetime.now()
        if date_str:
            try:
                date = parsedate_to_datetime(date_str)
            except Exception:
                pass

        # Extract Message-ID and References headers for proper threading
        message_id = email_message.get("Message-ID", "")
        references = email_message.get("References", "")

        body = self._get_body(email_message)
        return Email(
            id=email_id.decode(),
            from_address=from_address,
            to_address=to_address,
            subject=subject,
            body=body,
            message_id=message_id,
            references=references,
            date=date,
        )

    def _get_email_thread(
        self, imap_conn: imaplib.IMAP4_SSL, email_id_bytes: bytes
    ) -> List[Email]:
        email = self._parse_email(imap_conn, email_id_bytes)
        if not email:
            return []

        thread = [email]

        # Try thread via X-GM-THRID (Gmail extension)
        _, thrid_data = imap_conn.fetch(email.id, "(X-GM-THRID)")
        match = None
        if thrid_data and thrid_data[0]:
            data = thrid_data[0]
            if isinstance(data, bytes):
                match = re.search(r"X-GM-THRID\s+(\d+)", data.decode())
            else:
                match = re.search(r"X-GM-THRID\s+(\d+)", str(data))
        if match:
            thread_id = match.group(1)
            _, thread_ids = imap_conn.search(None, f"X-GM-THRID {thread_id}")
            if thread_ids and thread_ids[0]:
                thread = [
                    self._parse_email(imap_conn, mid) for mid in thread_ids[0].split()
                ]
                thread = [e for e in thread if e]
                thread.sort(key=lambda e: e.date)
                return thread

        # Fallback: use REFERENCES header
        _, ref_data = imap_conn.fetch(
            email.id, "(BODY.PEEK[HEADER.FIELDS (REFERENCES)])"
        )
        if ref_data and ref_data[0]:
            ref_line = (
                ref_data[0][1].decode() if isinstance(ref_data[0][1], bytes) else ""
            )
            refs = re.findall(r"<([^>]+)>", ref_line)
            for ref in refs:
                _, ref_ids = imap_conn.search(None, f'(HEADER Message-ID "<{ref}>")')
                if ref_ids and ref_ids[0]:
                    for ref_id in ref_ids[0].split():
                        ref_email = self._parse_email(imap_conn, ref_id)
                        if ref_email and ref_email.id not in [e.id for e in thread]:
                            thread.append(ref_email)

            # Sort emails in the thread by date (ascending order)
            thread.sort(key=lambda e: e.date)
            return thread

        return thread

    def _get_unread_emails(self, imap_conn: imaplib.IMAP4_SSL) -> List[List[Email]]:
        imap_conn.select("INBOX")
        _, msg_nums = imap_conn.search(None, f'(UNSEEN TO "{self.support_address}")')
        emails: List[List[Email]] = []

        for email_id in msg_nums[0].split():
            thread = self._get_email_thread(imap_conn, email_id)
            emails.append(thread)

        return emails

    def mark_as_read(self, imap_conn: imaplib.IMAP4_SSL, message_id: str):
        imap_conn.store(message_id, "+FLAGS", "\\Seen")

    def get_email_thread(self, email_id: str) -> List[Email]:
        # Get IMAP connection
        imap_conn = self._ensure_imap_connection()

        # Make sure we're in the INBOX
        imap_conn.select("INBOX")

        # Get the thread
        thread = self._get_email_thread(
            imap_conn=imap_conn, email_id_bytes=email_id.encode()
        )

        return thread

    async def process(
        self,
        respond: Callable[[List[Email]], Awaitable[Union[Email, None]]],
        mark_read: bool = True,
    ):
        try:
            # Get IMAP connection
            imap_conn = self._ensure_imap_connection()

            # Get unread emails
            print("Fetching unread emails...")
            unread_emails = self._get_unread_emails(imap_conn)

            # Only connect to SMTP if there are unread emails
            if not unread_emails:
                print("No unread emails found, skipping SMTP connection")
                return

            # Connect to SMTP server only if we have emails to respond to
            print("Unread emails found, connecting to SMTP server...")
            try:
                smtp_conn = self._connect_to_smtp()
            except Exception as e:
                print(f"Failed to connect to SMTP server: {str(e)}")
                return

            for email_thread in unread_emails:
                # Get the most recent email in the thread
                most_recent = email_thread[-1]

                # Generate the response
                response = await respond(email_thread)

                # If there is no response, skip this email and keep as unread
                # in the inbox
                if response is None:
                    continue

                # Send the response
                # Get the most recent email in the thread to reply to
                print(
                    f"Replying to '{response.to_address}' from '{self.email_address}':\n  {json.dumps(response.body)}"
                )

                # Set the message_id and references from the original email for proper threading
                response.message_id = most_recent.message_id
                response.references = most_recent.references

                # Send the message with retry mechanism
                message = response.to_message(self.support_address)

                # Retry up to 3 times with increasing delays
                max_retries = 3
                retry_delay = 2
                success = False

                for attempt in range(1, max_retries + 1):
                    try:
                        # Make sure the connection is still alive
                        try:
                            smtp_conn.noop()
                        except:
                            print(f"SMTP connection lost, reconnecting (attempt {attempt})...")
                            smtp_conn = self._connect_to_smtp()

                        # Send the message with a larger data block size
                        smtp_conn.send_message(message)
                        print(f"Email sent successfully with headers: From={message['From']}, To={message['To']}, CC={message['Cc']}")
                        success = True
                        break
                    except smtplib.SMTPServerDisconnected:
                        print(f"SMTP server disconnected, reconnecting (attempt {attempt})...")
                        smtp_conn = self._connect_to_smtp()
                    except smtplib.SMTPResponseException as e:
                        if e.smtp_code == 451:  # Timeout error
                            print(f"SMTP timeout error (451), retrying in {retry_delay}s (attempt {attempt})...")
                            await asyncio.sleep(retry_delay)
                            retry_delay *= 2  # Exponential backoff
                            # Reconnect to SMTP server
                            smtp_conn = self._connect_to_smtp()
                        else:
                            print(f"SMTP error: {e.smtp_code} {e.smtp_error}, retrying in {retry_delay}s (attempt {attempt})...")
                            await asyncio.sleep(retry_delay)
                            retry_delay *= 2
                    except Exception as e:
                        print(f"Error sending email (attempt {attempt}): {str(e)}")
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 2

                # Skip marking as read if sending failed
                if not success:
                    print(f"Failed to send email after {max_retries} attempts, skipping this message")
                    continue

                # Mark the original email as read
                if mark_read:
                    self.mark_as_read(imap_conn, most_recent.id)

            # Close SMTP connection
            try:
                smtp_conn.quit()
            except:
                print("Error when closing SMTP connection, ignoring")

        except Exception as e:
            print(f"Error during email processing: {str(e)}")
            # Reset IMAP connection on error
            if self.imap_conn:
                try:
                    self.imap_conn.logout()
                except:
                    pass
                self.imap_conn = None

    async def run(
        self,
        respond: Callable[[List[Email]], Awaitable[Union[Email, None]]],
        mark_read: bool = True,
        delay: int = 60,
    ):
        try:
            while True:
                # Process emails
                await self.process(respond, mark_read)
                # Wait before next check
                print(f"Sleeping for {delay}s...")
                await asyncio.sleep(delay)
        finally:
            # Ensure we close the IMAP connection when the program exits
            if self.imap_conn:
                try:
                    self.imap_conn.logout()
                    print("IMAP connection closed")
                except:
                    pass
                self.imap_conn = None
