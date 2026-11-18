# Working rules (tuned profile for droid, see droid.sim.json for why each rule exists)

1. Files you write must be valid. After writing answer.json, run `python3 -m json.tool answer.json`. If it fails, rewrite the file. Never end the file with an extra `}` or `]`.
2. Copy every key name from the task text letter for letter. Do not rename or re-spell keys.
3. If the task asks for a program (analyze.py or similar), do not only read the data. Create the program, run it on the given input, then check the output file exists.
4. Check your work once, then stop. Do not rewrite a file that is already correct.
5. Reading a file is not finishing. Finish only when every requested output file exists and has been checked.
