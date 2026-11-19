import json, os, requests
os.makedirs("dump20", exist_ok=True)
s = requests.Session()
B = "https://data.calgary.ca"
out = {}
out["meta_columns"] = [(c.get("fieldName"), c.get("name"), c.get("dataTypeName")) for c in s.get(f"{B}/api/views/ruq3-99hx.json", timeout=60).json().get("columns", [])]
out["blank_voter_sample"] = s.get(f"{B}/resource/ruq3-99hx.json", params={"$where": "voter IS NULL", "$limit": 8}, timeout=60).json()
out["blank_count"] = s.get(f"{B}/resource/ruq3-99hx.json", params={"$select": "count(*)", "$where": "voter IS NULL"}, timeout=60).json()
out["by_year_blank"] = s.get(f"{B}/resource/ruq3-99hx.json", params={"$select": "date_extract_y(meetingdate) as y, count(*)", "$where": "voter IS NULL", "$group": "y"}, timeout=60).json()
out["by_year_all"] = s.get(f"{B}/resource/ruq3-99hx.json", params={"$select": "date_extract_y(meetingdate) as y, count(*)", "$group": "y"}, timeout=60).json()
out["sample_2020"] = s.get(f"{B}/resource/ruq3-99hx.json", params={"$where": "meetingdate < '2020-10-01'", "$limit": 5}, timeout=60).json()
json.dump(out, open("dump20/summary.json", "w"), indent=1)
