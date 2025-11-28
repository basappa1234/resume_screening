# Vercel serverless function entry point
import sys
import os

# Add backend directory to Python path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'backend'))

# Import the Flask app
from app import app

# Vercel expects the application to be named 'application'
application = app