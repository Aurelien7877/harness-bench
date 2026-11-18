Read contacts.json, a list of email strings that may be empty. Two emails are the same when they match after trimming spaces and lowercasing. Return unique, the number of distinct emails, and duplicates, the number of discarded repeats.
Output exactly these fields (JSON object order does not matter): {"unique": "number", "duplicates": "number"}
Write analyze.py accepting INPUT_PATH OUTPUT_JSON_PATH. Run it on contacts.json and save answer.json. The verifier checks that saved answer and runs your program on public and held-out inputs with the same schema. Use only the supplied input; do not hardcode its answer.
Work in /workspace. Do not install packages or use the network.
