#!/bin/bash

# Setup script for Python backend

echo "Setting up Python backend for Resume Parser..."

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip

# Install dependencies
echo "Installing dependencies..."
pip install -r requirements.txt

# Create temp directory for uploads
if [ ! -d "temp_uploads" ]; then
    mkdir temp_uploads
fi

echo "Setup complete!"
echo "To start the server, run:"
echo "source venv/bin/activate && python app.py"
