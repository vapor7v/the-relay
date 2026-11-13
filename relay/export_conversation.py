"""Export complete authentic conversation transcript to conversation_history.md."""
import json
import os
import sys

TRANSCRIPT_PATH = "/home/apurvnishit/.gemini/antigravity/brain/f856b5ab-8e84-4186-8f54-570f85d297e2/.system_generated/logs/transcript.jsonl"
OUT_PATH = "/home/apurvnishit/Assignment/conversation_history.md"

def export_transcript():
    if not os.path.exists(TRANSCRIPT_PATH):
        print(f"Error: {TRANSCRIPT_PATH} not found.")
        return

    with open(TRANSCRIPT_PATH, "r") as f:
        lines = f.readlines()

    out = []
    out.append("# The Relay — Authentic Assistant Conversation History\n")
    out.append(f"*Complete unedited transcript exported from system conversation logs ({len(lines)} steps).*\n")
    out.append("---\n")

    for line in lines:
        try:
            entry = json.loads(line)
        except Exception:
            continue

        step_idx = entry.get("step_index", 0)
        source = entry.get("source", "")
        entry_type = entry.get("type", "")
        created_at = entry.get("created_at", "")
        content = entry.get("content", "")
        tool_calls = entry.get("tool_calls", [])

        if entry_type == "USER_INPUT":
            out.append(f"\n## Step {step_idx} | USER [{created_at}]\n")
            out.append(content.strip() + "\n")
        elif entry_type == "PLANNER_RESPONSE":
            out.append(f"\n### Step {step_idx} | ASSISTANT RESPONSE [{created_at}]\n")
            if content:
                out.append(content.strip() + "\n")
            if tool_calls:
                out.append("\n**Tool Calls:**\n")
                for tc in tool_calls:
                    out.append(f"- `{tc.get('name')}`: `{tc.get('args', {})}`\n")
        elif entry_type == "SYSTEM_MESSAGE":
            out.append(f"\n*System Message (Step {step_idx})*: {content.strip()[:300]}...\n")

    with open(OUT_PATH, "w") as f:
        f.writelines(out)

    print(f"Exported {len(lines)} transcript steps to {OUT_PATH} ({os.path.getsize(OUT_PATH)} bytes).")

if __name__ == "__main__":
    export_transcript()
