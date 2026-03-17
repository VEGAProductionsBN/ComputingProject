import asyncio
import aiohttp
import json

HA_URL = "http://homeassistant.local:8123"
TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiI1ZTYxYzgwODY5NjY0ZjZkODQ1YjY5NTZkZWRiMDI2YiIsImlhdCI6MTc3MzMyMTQ4MCwiZXhwIjoyMDg4NjgxNDgwfQ.QPcRgynFSwWlpP0t1HuHg-nECBoyfA43-bGYCzepm2A"
ENTITY_ID = "light.eveready_rgbcct_led_bc_gls"

async def monitor_light():
    previous_brightness = None
    previous_color = None
    previous_last_changed = None

    while True:
        headers = {
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{HA_URL}/api/states/{ENTITY_ID}", headers=headers) as resp:
                data = await resp.json()
                attributes = data.get('attributes', {})
                brightness = attributes.get('brightness')
                color_mode = attributes.get('color_mode')
                
                if color_mode == 'color_temp':
                    color = f"Color Temp: {attributes.get('color_temp_kelvin')}K"
                elif color_mode == 'hs':
                    color = f"HS: {attributes.get('hs_color')}"
                else:
                    color = "Unknown"
                
                last_changed = data.get('last_changed')
                
                if brightness != previous_brightness or color != previous_color or last_changed != previous_last_changed:
                    print(f"Brightness: {brightness}")
                    print(f"Colour: {color}")
                    print(f"Time changed: {last_changed}")
                    print("---")
                    
                    previous_brightness = brightness
                    previous_color = color
                    previous_last_changed = last_changed
        
        await asyncio.sleep(1)  # Poll every 1 second

asyncio.run(monitor_light())