#!/bin/bash

# Script to set up environment files from templates

# Function to create .env file from template if it doesn't exist
create_env_from_template() {
    local template_file=$1
    local env_file=${template_file/.template/}

    if [ ! -f "$env_file" ]; then
        echo "Creating $env_file from template..."
        cp "$template_file" "$env_file"
        echo "Please edit $env_file with your API keys and other settings."
    else
        echo "$env_file already exists. Skipping."
    fi
}

# Create .env files from templates
create_env_from_template "agents/langchain/.env.template"
create_env_from_template "agents/crewai/.env.template"
create_env_from_template "agents/openai/.env.template"
create_env_from_template "agents/openai/customer_support/.env.template"
create_env_from_template "agents/openai/web_search/.env.template"

echo "Environment setup complete. Please edit the .env files with your API keys before running the containers."
