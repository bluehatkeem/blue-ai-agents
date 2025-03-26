# Email Support Agent

Sample app to help you automate your email support. Powered by OpenAI's Agent SDK and [Stripe Agent Toolkit](https://github.com/stripe/agent-toolkit).

Customize this agent to fit your own needs by cloning and modifying [support_agent.py](./support_agent.py).

## Features

The support agent currently can:

- Answer FAQ questions
- Update billing information through Customer Portal
- Send any missing invoices
- Integrate with Telegram for manual approval of responses
- Save drafts instead of sending emails directly

We also support a REPL to help you test your agent without sending a gazillion emails.

## How it Works

The support agent will:

- Connects to your email using an IMAP client
- Checks for unread emails every 30 seconds
- Generates a draft reply
- Sends the draft to a Telegram bot for review (if configured)
- Based on Telegram feedback, either:
  - Sends the email response
  - Saves the email as a draft
- Marks the emails as read

If it doesn't know how to answer the question, it will not respond and ignore the email.

## Setup

1. Install uv (if not already installed):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

2. Clone this repository
3. Create and activate a virtual environment:

```bash
uv venv
source .venv/bin/activate  # On Unix/macOS
# or
.venv\Scripts\activate  # On Windows
```

4. Install dependencies:

```bash
uv sync
```

5. Copy `.env.agent` to `.env`:

```bash
cp .env.agent .env
```

6. Configure your `.env` file with:
   - Email credentials (create an [app-specific password](https://support.google.com/accounts/answer/185833) for Gmail)
   - IMAP/SMTP server details (defaults for Gmail provided in .env.agent)
   - OpenAI API key
   - Stripe Secret Key
   - Telegram Bot settings (optional)

### Telegram Bot Setup (Optional)

To use the Telegram integration:

1. Create a new bot using [BotFather](https://t.me/botfather) and get the token
2. Add the token to your `.env` file as `TELEGRAM_BOT_TOKEN`
3. Get your chat ID using [@userinfobot](https://t.me/userinfobot) and add it to `.env` as `TELEGRAM_CHAT_ID`
4. For additional security, add admin user IDs as a comma-separated list in `TELEGRAM_ADMIN_IDS`

When configured, the agent will:
1. Send a message with email details and the proposed response to your Telegram
2. Provide buttons to "Send Response" or "Save as Draft"
3. Wait for your decision before proceeding

## Usage

Run the agent:

```bash
python main.py
```

Run the REPL with:

```bash
python repl.py
```

## Customize for your App

This repository is just a sample app tailored to our [agent website](http://standupjack.com).

We recommend cloning this repository and customizing the system prompt and tools in [support_agent.py](./support_agent.py). It's very easy to add new capabilities.
