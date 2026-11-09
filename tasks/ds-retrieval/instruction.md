Evaluate rankings with non-empty binary relevance and distinct result IDs. Compute mean recall@3 and mean reciprocal rank@3. Ignore results after rank 3. Round to 6 decimals. Output recall_a, recall_b, mrr_a, mrr_b, winner (a/b/tie), choosing recall then MRR.
Write analyze.py accepting INPUT_PATH OUTPUT_JSON_PATH. Run it on rankings.json and save answer.json. The verifier will also run your program on another input with the same schema.
Work in /workspace. Do not install packages or use the network.

MRR definition: for each query, take 1 divided by the one-based rank of the FIRST relevant result among the first three, or zero if absent. Average these values across queries. MRR must be between 0 and 1.
