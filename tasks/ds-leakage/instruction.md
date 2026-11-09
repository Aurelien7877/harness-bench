Audit experiment.json before approving a churn model. The prediction timestamp is month start and the evaluation should simulate future unseen customers. Return leakage_columns (alphabetically sorted), split_policy chosen from random/time_group, fit_preprocessor_on chosen from all/train, reported_accuracy_trustworthy boolean. No model training is required.
Write answer.json with these fields and types:
{"leakage_columns": "list", "split_policy": "str", "fit_preprocessor_on": "str", "reported_accuracy_trustworthy": "bool"}
Work in /workspace. Do not install packages or use the network.
