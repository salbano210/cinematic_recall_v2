import asyncio, sys
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv()
from sqlalchemy import text
from db import engine

async def main():
    print('db url host:', str(engine.url).split('@')[-1].split('/')[0])
    async with engine.connect() as conn:
        rows = (await conn.execute(text('SELECT email, created_at FROM users ORDER BY created_at DESC LIMIT 5'))).all()
        print('USERS:')
        for e, c in rows:
            print(c, '|', e)

asyncio.run(main())