import os

from dotenv import load_dotenv


# Load environment variables from the project's .env file.
load_dotenv(override=True)

# Read Smarty API credentials without printing or logging secret values.
SMARTY_AUTH_ID = os.getenv("SMARTY_AUTH_ID")
SMARTY_AUTH_TOKEN = os.getenv("SMARTY_AUTH_TOKEN")


# Stop application startup when the Smarty authentication ID is missing.
if not SMARTY_AUTH_ID:
    raise ValueError(
        "SMARTY_AUTH_ID is missing from the environment configuration."
    )

# Stop application startup when the Smarty authentication token is missing.
if not SMARTY_AUTH_TOKEN:
    raise ValueError(
        "SMARTY_AUTH_TOKEN is missing from the environment configuration."
    )