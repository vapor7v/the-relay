"""Run remaining stand-in scenarios (burst, sustained_overload, per_minute_limit_halved, daily_budget_exhausted)."""
import asyncio
import os
import sys
import json

sys.path.insert(0, os.path.dirname(__file__))

from runner import run_scenario, RateLimiterConfig
from simulator import run_simulator, _global_state


async def main():
    # Start calibrated simulator with target production limits: RPM=60, TPM=7000
    run_simulator(seed=42)
    from simulator import _global_state
    if _global_state:
        _global_state.cal["rpm_limit"] = 60
        _global_state.cal["tpm_limit"] = 7000

    scenarios = []

    # Read existing scenario summary (e.g. steady) if present
    summary_path = os.path.join(os.path.dirname(__file__), "scenarios_summary.json")
    if os.path.exists(summary_path):
        try:
            with open(summary_path) as f:
                scenarios = json.load(f)
        except Exception:
            pass

    # Filter out any old simulated runs if re-running
    scenarios = [s for s in scenarios if s["scenario"] == "steady"]

    # Scenario 2: Burst (stand-in)
    # 5 steady requests + 15 simultaneous burst requests at t=2.0s
    print("\n--- Running Scenario 2: Burst (stand-in) ---")
    s_burst = await run_scenario(
        name="burst",
        num_requests=5,
        rate_per_minute=10,
        duration_s=30,
        use_simulator=True,
        burst_at=2.0,
        burst_count=15,
    )
    scenarios.append(s_burst)

    # Scenario 3: Sustained Overload (stand-in)
    # 25 requests arriving at 120 requests/minute
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
    # 10 requests arriving at 30/min, with client token bucket cut in half (RPM=15, TPM=3500)
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
    # Starts with an already exhausted daily budget (0 remaining)
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

    with open(summary_path, "w") as f:
        json.dump(scenarios, f, indent=2)

    print(f"\nAll scenarios completed and written to {summary_path}!")


if __name__ == "__main__":
    asyncio.run(main())
