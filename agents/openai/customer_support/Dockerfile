FROM python:3.11-slim

WORKDIR /app

# Copy the project files
COPY stripe_agent_toolkit/ /app/stripe_agent_toolkit/
COPY pyproject.toml requirements.txt /app/
COPY agents/openai/customer_support/ /app/agents/openai/customer_support/

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir -e .
# Install agent-specific dependencies
RUN pip install --no-cache-dir "markdown==3.7" "python-dotenv>=1.0.0" "imaplib2==3.6" "python-decouple==3.8" "urllib3<2.0.0" "python-telegram-bot==20.7"

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Default command
CMD ["python", "/app/agents/openai/customer_support/main.py"]
