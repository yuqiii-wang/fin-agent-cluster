"""Test script for AAPL query."""
import asyncio
import httpx
import json


async def test_aapl():
    """Test the financial analysis graph with AAPL."""
    base_url = "http://localhost:8432"
    
    async with httpx.AsyncClient(timeout=120) as client:
        # Health check
        print("Checking health...")
        health = await client.get(f"{base_url}/health")
        print(f"Health status code: {health.status_code}")
        print(f"Health content: {health.text}")
        
        if health.status_code != 200:
            print("Health check failed, continuing anyway...")
        
        # Submit AAPL query
        print("\nSubmitting AAPL query...")
        response = await client.post(
            f"{base_url}/query",
            json={"query": "Evaluate AAPL stock", "user_id": "test_user"}
        )
        
        print(f"Response status code: {response.status_code}")
        print(f"Response content: {response.text}")
        
        if response.status_code != 200:
            print(f"Error: {response.status_code}")
            return
        
        result = response.json()
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    asyncio.run(test_aapl())
