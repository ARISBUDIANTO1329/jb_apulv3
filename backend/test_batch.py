import os, json, asyncio, httpx
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import text

async def test():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with AsyncSession(engine) as db:
        # Get settings
        r = await db.execute(text("SELECT provider, base_url, api_key, model FROM ai_settings LIMIT 1"))
        s = r.mappings().first()
        
        # Get channel 1 videos with issues
        r2 = await db.execute(text("""
            SELECT filename FROM ai_issues 
            WHERE channel_id = 1 AND status = 'open' 
            ORDER BY detected_at DESC LIMIT 5
        """))
        issues = [row[0] for row in r2]
        print(f"Issues: {issues}")
        
        # Build simple test prompt
        prompt = '''Return a JSON array with 3 YouTube title suggestions for a relaxation music channel.
Format: [{"id":"test","titles":["A","B","C"],"desc":"test desc","tags":["tag1"],"reason":"test"}]
Return ONLY the JSON array, nothing else.'''
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{s['base_url']}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {s['api_key']}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": s["model"],
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 2000,
                        "stream": False,
                    },
                )
                print(f"Status: {resp.status_code}")
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                print(f"Response ({len(content)} chars):")
                print(content[:500])
                
                # Try parse
                import re
                json_match = re.search(r'\[.*\]', content, re.DOTALL)
                if json_match:
                    parsed = json.loads(json_match.group(0))
                    print(f"\nParsed OK: {len(parsed)} items")
                else:
                    print("\nNo JSON array found in response")
        except Exception as e:
            print(f"Error: {type(e).__name__}: {e}")

asyncio.run(test())
