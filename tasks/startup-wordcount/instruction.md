Read a text file that may be empty. Write a reusable script that returns the number of whitespace-separated words and the number of lines.
Output exactly these fields (JSON object order does not matter): {"words": "number", "lines": "number"}
Write analyze.py accepting INPUT_PATH OUTPUT_JSON_PATH. Run it on text.txt and save answer.json. The verifier checks that saved answer and runs your program on public and held-out inputs with the same schema. Use only the supplied input; do not hardcode its answer.
Work in /workspace. Do not install packages or use the network.
