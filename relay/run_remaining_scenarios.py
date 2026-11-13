import asyncio
import os
import sys
import json

sys.path.insert(0, os.path.dirname(__file__))

from runner import run_scenario, RateLimiterConfig
from simulator import run_simulator

async def main():
    run_simulator()
    scenarios = []

    # Scenario 3: Sustained Overload (stand-in)
    print("\n--- Running Scenario 3: Sustained Overload (stand-in) ---")
    s_overload = await run_scenario(
        name="sustained_overload",
        num_requests=25,
        rate_per_minute=120,
        duration_s=20,
        use_simulator=True,
    )
    scenarios.append(s_overload)

    # Scenario 4: Per-minute limit halved (stand-in)
    print("\n--- Running Scenario 4: Per-minute limit halved (stand-in) ---")
    s_halved = await run_scenario(
        name="per_minute_limit_halved",
        num_requests=10,
        rate_per_minute=30,
        duration_s=30,
        use_simulator=True,
        rl_config=RateLimiterConfig(rpm=15, tpm=3500),
    )
    scenarios.append(s_halved)

    # Scenario 5: Daily budget exhausted (stand-in)
    print("\n--- Running Scenario 5: Daily budget exhausted (stand-in) ---")
    s_exhausted = await run_scenario(
        name="daily_budget_exhausted",
        num_requests=10,
        rate_per_minute=10,
        duration_s=20,
        use_simulator=True,
        pre_exhaust_daily=True,
    )
    scenarios.append(s_exhausted)

    with open("scenarios_3_4_5.json", "w") as f:
        json.dump(scenarios, f, indent=2)

    print("\n\nScenarios 3, 4, 5 complete! Saved to scenarios_3_4_5.json")

if __name__ == "__main__":
    asyncio.run(main())
