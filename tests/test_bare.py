from adapters.bare import extract, target_file


def test_reply_becomes_the_named_file():
    assert extract('Here:\n```json\n{"a": 1}\n```\nDone') == '{"a": 1}\n'
    assert extract('{"a": 1}') == '{"a": 1}\n'
    assert target_file('Write answer.json with these fields', '') == 'answer.json'
    assert target_file('Complete candidate.py according', '') == 'candidate.py'
    assert target_file('Fix stats_utils.py so test_stats_utils.py passes', '') == 'stats_utils.py'
    assert target_file('Write roman.py with two functions. check_roman.py must print OK', '') == 'roman.py'
