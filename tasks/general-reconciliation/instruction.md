Apply payments to invoices oldest first, within each customer only. Deduplicate payments by payment_id, keeping first. Amounts are integer cents. Report remaining invoice balances as balances, unapplied_credit by customer, duplicate_payments count. Read ledger.json.
Write answer.json with these fields and types:
{"balances": "dict", "unapplied_credit": "dict", "duplicate_payments": "int"}
Work in /workspace. Do not install packages or use the network.
