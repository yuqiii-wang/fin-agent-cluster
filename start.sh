#!/bin/bash
set -e

# Check for .env file
if [ ! -f .env ]; then
  echo "Error: .env file not found"
  exit 1
fi

# Start the FastAPI server
python run.py
