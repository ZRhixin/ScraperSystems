import asyncio
import os
os.environ["SCRAPER_DEBUG"] = "1"

from propertyvaluescraper.property_value_scraper import scrape_all

ADDRESS = "2896 NC 903 N, Stokes, NC 27884"

result = asyncio.run(scrape_all(ADDRESS))
print(result)
