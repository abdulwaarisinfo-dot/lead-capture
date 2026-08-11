"""
Runs evals/cases.json against the running /api/triage endpoint and prints a
score on the `category` field. Requires the server to be running:

    uvicorn index:app --reload

Then in another terminal:

    python evals/run_eval.py
"""
import json
import sys
from pathlib import Path
import urllib.request

ENDPOINT = "http://127.0.0.1:8000/api/triage"
CASES_PATH = Path(__file__).parent / "cases.json"


def call(message: str) -> dict:
    data = json.dumps({"message": message}).encode()
    req = urllib.request.Request(
        ENDPOINT, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=40) as resp:
        return json.loads(resp.read())


def main():
    cases = json.loads(CASES_PATH.read_text())
    correct = 0
    failures = []

    for i, case in enumerate(cases, 1):
        try:
            body = call(case["input"])
        except Exception as e:
            failures.append((case["input"], f"request error: {e}"))
            continue

        if not body.get("success"):
            failures.append((case["input"], f"endpoint error: {body.get('error')}"))
            continue

        got = body["result"]["category"]
        expected = case["expected_category"]
        if got == expected:
            correct += 1
        else:
            failures.append((case["input"], f"expected {expected}, got {got}"))

        print(f"[{i}/{len(cases)}] expected={expected} got={got} {'OK' if got == expected else 'MISS'}")

    print(f"\nScore: {correct}/{len(cases)} on category field")
    if failures:
        print("\nFailures:")
        for inp, reason in failures:
            print(f"  - {inp!r}: {reason}")


if __name__ == "__main__":
    main()
