import asyncio
import aiohttp
import json

HA_URL = "http://homeassistant.local:8123"
TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiI1ZTYxYzgwODY5NjY0ZjZkODQ1YjY5NTZkZWRiMDI2YiIsImlhdCI6MTc3MzMyMTQ4MCwiZXhwIjoyMDg4NjgxNDgwfQ.QPcRgynFSwWlpP0t1HuHg-nECBoyfA43-bGYCzepm2A"
ENTITY_ID = "light.eveready_rgbcct_led_bc_gls"

async def get_light_metadata():
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{HA_URL}/api/states/{ENTITY_ID}", headers=headers) as resp:
            data = await resp.json()
            print(json.dumps(data, indent=4))

asyncio.run(get_light_metadata())

asyncio.run(get_light_metadata())