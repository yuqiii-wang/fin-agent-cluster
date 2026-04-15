#!/bin/bash
set -e

# Make sure you are in the ollama directory
cd "$(dirname "$0")"

echo "Building the Qwen3.5-27B model for Ollama..."
ollama create qwen3.5-27b-instruct -f Modelfile

echo "Building the Qwen3-0.6B embedding model for Ollama..."
ollama create qwen3-0.6b-emb -f Modelfile.embed

echo "Starting the model interactively..."
ollama run qwen3.5-27b-instruct
