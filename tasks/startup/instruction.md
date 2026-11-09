Read a JSON array of integers, which may be empty and may contain negative values. Write a reusable script that returns count and sum. An empty array has count 0 and sum 0.
Output exactly these fields (JSON object order does not matter): {"count": "number", "sum": "number"}
Write analyze.py accepting INPUT_PATH OUTPUT_JSON_PATH. Run it on numbers.json and save answer.json. The verifier checks that saved answer and runs your program on public and held-out inputs with the same schema. Use only the supplied input; do not hardcode its answer.
Work in /workspace. Do not install packages or use the network.
