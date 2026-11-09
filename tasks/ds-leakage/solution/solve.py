from pathlib import Path
Path('answer.json').write_text('{"leakage_columns": ["cancellation_reason", "days_until_churn"], "split_policy": "time_group", "fit_preprocessor_on": "train", "reported_accuracy_trustworthy": false}')
