# Containerized Stripe Agent Toolkit agents

This directory contains Docker configurations for running all the customer support agent in the Stripe Agent Toolkit.

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/)
- [Docker Compose](https://docs.docker.com/compose/install/)

## Setup

1. Clone this repository:
   ```
   git clone https://github.com/bluehatkeem/blue-ai-agents.git
   cd blue-ai-agents
   ```

2. Set up environment files from templates:
   ```
   ./setup_env.sh
   ```

3. Edit the created `.env` file with your API keys and other required settings:
   - `agents/openai/customer_support/.env`


## Running the agents

You can run/build agents with Docker compose:

```

#### OpenAI Customer Support agent

```
docker-compose up  --build openai-customer-support -d
```


## Building Individual Images

If you want to build and run a specific agent without using Docker Compose:

```
# Build the image
docker build -f agents/openai/customer_support/Dockerfile -t openai-customer-support .

# Run the container
docker run --env-file agents/openai/customer_support/.env openai-customer-support
```

## Customizing the agents

Each agent has its own Dockerfile and can be customized as needed. The Docker Compose file mounts the agent directories as volumes, so you can make changes to the code and see them reflected immediately without rebuilding the images.

## Dependencies

The Dockerfiles are configured to install:
1. The main project dependencies from `requirements.txt`
2. The Stripe Agent Toolkit package itself
3. Any agent-specific dependencies defined in the agent's own `requirements.txt` or `pyproject.toml` files

Some agents (like the OpenAI Customer Support agent) have their own dependencies defined in their directories. These are automatically installed during the Docker build process.

## Troubleshooting

- If you encounter permission issues, make sure the `.env` files have the correct permissions.
- If you see errors related to missing API keys, make sure you've properly set up the `.env` files.
- If you need to rebuild the images, use `docker-compose build` or `docker-compose up --build`.
- If you encounter missing dependency errors, check if the agent has specific dependencies in its directory and make sure they're being installed correctly.
