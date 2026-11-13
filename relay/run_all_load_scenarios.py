"""Runner script to execute all 5 load scenarios and save scenarios_summary.json."""
import asyncio
import os
import sys
import json

sys.path.insert(0, os.path.dirname(__file__))

from runner import run_scenario, RateLimiterConfig
from simulator import run_simulator


async def main():
    run_simulator(seed=42)
    scenarios = []

    # Scenario 1: Steady (real Groq service with modest requests to learn limits)
    # Note: Requires BypassSandbox: true when running against live Groq API
    print("\n--- Running Scenario 1: Steady (real Groq) ---")
    s_steady = await run_scenario(
        name="steady",
        num_requests=5,
        rate_per_minute=10,
        duration_s=30,
        use_simulator=False,
    )
    scenarios.append(s_steady)

    # Scenarios 2-5 on calibrated stand-in simulator
    print("\n--- Running Scenario 2: Burst (stand-in) ---")
    s_burst = await run_scenario(
        name="burst",
        num_requests=5,
        rate_per_minute=10,
        duration_s=30,
        use_simulator=True,
        burst_at=3.0,
        burst_count=15,
    )
    scenarios.append(s_burst)

    print("\n--- Running Scenario 3: Sustained Overload (stand-in) ---")
    s_overload = await run_scenario(
        name="sustained_overload",
        num_requests=25,
        rate_per_minute=120,
        duration_s=20,
        use_simulator=True,
    )
    scenarios.append(s_overload)

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

    out_path = os.path.join(os.path.dirname(__file__), "scenarios_summary.json")
    with open(out_path, "w") as f:
        json.dump(scenarios, f, indent=2)

    print(f"\n\nAll 5 load scenarios completed successfully! Summary saved to {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
