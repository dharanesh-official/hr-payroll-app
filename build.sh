#!/usr/bin/env bash
# exit on error
set -o errexit

# Install the Python libraries
pip install -r requirements.txt

# Run the database initialization command
flask init-db