"""Run Scenario 1: Steady on real Groq service."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from runner import run_scenario

async def main():
    print("\n--- Running Scenario 1: Steady (real Groq service) ---")
    s_steady = await run_scenario(
        name="steady",
        num_requests=5,
        rate_per_minute=10,
        duration_s=30,
        use_simulator=False,
    )
    print("Steady scenario complete:", s_steady)

if __name__ == "__main__":
    asyncio.run(main())
