"""
LLM Call Logger — Records every LLM interaction for inspection.

Every time a module calls the LLM, it should use this logger to record:
  - Full prompt (what we sent)
  - Full response (what we got back)
  - Model used, module name, timestamp, token counts

Logs are saved as individual JSON files in output/llm_logs/ so you can
inspect exactly what went in and what came out for any LLM call.

Usage:
    from llm.llm_logger import call_llm

    # Instead of:  response = llm.invoke(prompt)
    # Use:         response = call_llm(llm, prompt, module="summarizer")

    # That's it. The logger wraps the call, saves the log, and returns the response.
"""

import json
import time
from datetime import datetime
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config.paths import LLM_LOGS, ensure_output_dirs


def call_llm(llm, prompt, module="unknown", metadata=None):
    """
    Call the LLM and log the full interaction.

    Args:
        llm:       The LangChain LLM object (from make_llm())
        prompt:    The prompt string to send
        module:    Name of the calling module (e.g. "summarizer", "claim_extractor")
        metadata:  Optional dict of extra context to include in the log

    Returns:
        The raw response text (string), same as llm.invoke(prompt).content
    """
    ensure_output_dirs()

    # Record start time
    start_time = time.time()
    timestamp = datetime.now().isoformat()

    # Make the actual LLM call
    response = llm.invoke(prompt)
    response_text = response.content.strip()

    # Calculate duration
    duration = round(time.time() - start_time, 2)

    # Extract model info
    model_name = getattr(llm, "model_name", None) or getattr(llm, "model", "unknown")

    # Rough token estimation (1 token ≈ 4 chars)
    input_chars = len(prompt)
    output_chars = len(response_text)
    est_input_tokens = input_chars // 4
    est_output_tokens = output_chars // 4

    # Build the log entry
    log_entry = {
        "timestamp": timestamp,
        "module": module,
        "model": model_name,
        "duration_seconds": duration,

        "input": {
            "prompt": prompt,
            "char_count": input_chars,
            "est_tokens": est_input_tokens,
        },

        "output": {
            "response": response_text,
            "char_count": output_chars,
            "est_tokens": est_output_tokens,
        },

        "totals": {
            "est_total_tokens": est_input_tokens + est_output_tokens,
        },
    }

    if metadata:
        log_entry["metadata"] = metadata

    # Save to file — one file per call, named for easy browsing
    date_str = datetime.now().strftime("%Y-%m-%d")
    time_str = datetime.now().strftime("%H%M%S")
    filename = f"{date_str}_{module}_{time_str}.json"
    filepath = LLM_LOGS / filename

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(log_entry, f, indent=2, ensure_ascii=False)

    # Print a compact summary to console
    print(f"  [llm_log] {module} | {model_name} | {est_input_tokens}→{est_output_tokens} tokens | {duration}s | {filepath.name}")

    return response_text
