import asyncio
import logging
import aiohttp
import websockets
import names
from websockets import WebSocketServerProtocol
from websockets.exceptions import ConnectionClosedOK
from datetime import datetime, timedelta
import argparse
from aiofile import async_open
from aiopath import AsyncPath

logging.basicConfig(level=logging.INFO)
log_file_path = AsyncPath("log.txt")

API_URL = "https://api.privatbank.ua/p24api/exchange_rates?json&date="

async def log_to_file(message):
    async with async_open(log_file_path, 'a') as afp:
        await afp.write(f"{datetime.now()} - {message}\n")

async def fetch_exchange_rate(session, date, currencies):
    try:
        formatted_date = date.strftime("%d.%m.%Y")
        async with session.get(API_URL + formatted_date) as response:
            if response.status != 200:
                return {formatted_date: "API request failed with status: " + str(response.status)}
            data = await response.json()
            return {formatted_date: data}
    except Exception as e:
        return {formatted_date: f"Failed to fetch data: {str(e)}"}

async def get_exchange(days=1, currencies=['USD', 'EUR']):
    async with aiohttp.ClientSession() as session:
        tasks = []
        for i in range(days):
            date = datetime.today() - timedelta(days=i+1)
            tasks.append(fetch_exchange_rate(session, date, currencies))
        results = await asyncio.gather(*tasks)
        
        exchange_info = []
        for result in results:
            date, data = list(result.items())[0]
            if isinstance(data, str):
                exchange_info.append(f"{date}: {data}")
            else:
                day_info = [f"{date}:"]
                for rate in data.get('exchangeRate', []):
                    if rate.get('currency') in currencies:
                        day_info.append(
                            f"{rate['currency']} - Продаж: {rate.get('saleRate')} грн, Купівля: {rate.get('purchaseRate')} грн"
                        )
                exchange_info.append("\n".join(day_info))
        
        return "\n\n".join(exchange_info)

class Server:
    clients = set()

    async def register(self, ws: WebSocketServerProtocol):
        ws.name = names.get_full_name()
        self.clients.add(ws)
        logging.info(f'{ws.remote_address} connects')

    

    async def unregister(self, ws: WebSocketServerProtocol):
        self.clients.remove(ws)
        logging.info(f'{ws.remote_address} disconnects')

    async def send_to_clients(self, message: str):
        if self.clients:
            [await client.send(message) for client in self.clients]


    async def ws_handler(self, ws: WebSocketServerProtocol):
        await self.register(ws)
        try:
            await self.distribute(ws)
        except ConnectionClosedOK:
            pass
        finally:
            await self.unregister(ws)

    async def distribute(self, ws: WebSocketServerProtocol):
        async for message in ws:
            await log_to_file(message)
            if message.lower().startswith("exchange"):
                try:
                    parts = message.split()
                    days = int(parts[1]) if len(parts) > 1 else 1
                    days = min(max(days, 1), 10)
                    currencies = parts[2:] if len(parts) > 2 else ['USD', 'EUR']
                    exchange = await get_exchange(days, currencies)
                    await self.send_to_clients(exchange)
                except ValueError:
                    await self.send_to_clients("Невірний формат команди. Використовуйте 'exchange <кількість днів> [валюти]'.")
            elif message == 'Hello server':
                await self.send_to_clients("Привіт мої карапузи!")
            else:
                await self.send_to_clients(f"{ws.name}: {message}")

async def main():
    server = Server()
    async with websockets.serve(server.ws_handler, 'localhost', 8080):
        await asyncio.Future()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Run a WebSocket server and fetch currency exchange rates.")
    parser.add_argument("--currencies", type=str, nargs="+", default=["USD", "EUR"],
                        help="List of currencies to include in the response (default: USD, EUR).")
    args = parser.parse_args()

    Server.currencies = args.currencies
    asyncio.run(main())