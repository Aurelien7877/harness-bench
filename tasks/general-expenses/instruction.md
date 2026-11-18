Read expenses.csv, which may have no rows. Amounts are integer cents. Return total_cents, the number of expense rows as count, and top_category, the category with the largest total (alphabetically first on ties, empty string if no rows).
Output exactly these fields (JSON object order does not matter): {"total_cents": "number", "count": "number", "top_category": "string"}
Write analyze.py accepting INPUT_PATH OUTPUT_JSON_PATH. Run it on expenses.csv and save answer.json. The verifier checks that saved answer and runs your program on public and held-out inputs with the same schema. Use only the supplied input; do not hardcode its answer.
Work in /workspace. Do not install packages or use the network.
