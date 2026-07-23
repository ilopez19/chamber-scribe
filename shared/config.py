import os
from dotenv import load_dotenv

# Load the configuration from the .env file
load_dotenv()
# allows us to access all the mongo DB variables and use them throughout the application
#safely
MONGO_URI = os.environ["MONGO_URI"]
MONGO_DB_NAME = os.environ["MONGO_DB_NAME"]
SCRAPE_INTERVAL_SECONDS = int(os.environ["SCRAPE_INTERVAL_SECONDS"])

print(MONGO_URI,MONGO_DB_NAME,SCRAPE_INTERVAL_SECONDS)