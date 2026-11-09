Clean the CSV: first id wins, then exclude cancelled and missing amounts; include refunds and zeros. Produce excluded_rows, net_total, by_region. Use decimal-safe arithmetic.
Write analyze.py accepting INPUT_PATH OUTPUT_JSON_PATH. Run it on sales.csv and save answer.json. The verifier will also run your program on another input with the same schema.
Work in /workspace. Do not install packages or use the network.
