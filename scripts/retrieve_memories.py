import requests
import json
import ijson

# WHEN YOU DELETE A PROJECT IT ALLOWS YOU TO MOVE MEMORIES TO ANOTHER PROJECT!!

url = "https://api.supermemory.ai/v3/documents/documents"

headers = {
    "Host": "api.supermemory.ai",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:146.0) Gecko/20100101 Firefox/146.0",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": "https://app.supermemory.ai/",
    "content-type": "application/json",
    "Origin": "https://app.supermemory.ai",
    "Sec-GPC": "1",
    "Connection": "keep-alive",
    "Cookie": "__Secure-better-auth.state=qpL0Sa5ed-dxnOQtt9E_wAPHigNh5XnA.%2FZd2X7fYjUo9Wl18%2FDB6XmDFS1XENfjSlcg7ElJxnrI%3D; __Secure-better-auth.session_token=Majhd338tWoXS4Y75p0VCeG3T6q17nYZ.hqNVdHLXEeNIzIbhvSM9pWDI1bi55PKABdUZSsxNMd0%3D; last-site-visited=https%3A%2F%2Fapp.supermemory.ai; ph_phc_ShqecfUPQgf16lWu6ZMUzduQvcWzCywrkCz5KHwmWsv_posthog=%7B%22distinct_id%22%3A%22YX7VXvE5KquHpvtA3fvmiu%22%2C%22%24sesid%22%3A%5B1767199647871%2C%22019b7544-786f-723e-b8bc-d2fd7ec111f6%22%2C1767198980191%5D%2C%22%24epp%22%3Atrue%2C%22%24initial_person_info%22%3A%7B%22r%22%3A%22%24direct%22%2C%22u%22%3A%22https%3A%2F%2Fconsole.supermemory.ai%2Flogin%22%7D%7D; __Secure-better-auth.session_data=eyJzZXNzaW9uIjp7InNlc3Npb24iOnsiZXhwaXJlc0F0IjoiMjAyNi0wMS0wN1QxNjozNTo1MS4zNzBaIiwidG9rZW4iOiJNYWpoZDMzOHRXb1hTNFk3NXAwVkNlRzNUNnExN25ZWiIsImNyZWF0ZWRBdCI6IjIwMjUtMTItMzFUMTY6MzU6NTEuMzcwWiIsInVwZGF0ZWRBdCI6IjIwMjUtMTItMzFUMTY6MzU6NTEuMzcwWiIsImlwQWRkcmVzcyI6IiIsInVzZXJBZ2VudCI6Ik1vemlsbGEvNS4wIChXaW5kb3dzIE5UIDEwLjA7IFdpbjY0OyB4NjQ7IHJ2OjE0Ni4wKSBHZWNrby8yMDEwMDEwMSBGaXJlZm94LzE0Ni4wIiwidXNlcklkIjoiWVg3Vlh2RTVLcXVIcHZ0QTNmdm1pdSIsImltcGVyc29uYXRlZEJ5IjpudWxsLCJhY3RpdmVPcmdhbml6YXRpb25JZCI6Ikd4cFFFUTY2SGJaUEpER3JYa05zOEwiLCJpZCI6IndKckNYUldYZ1R0eEU4d1hrUTNySnUifSwidXNlciI6eyJuYW1lIjoiRnJhbmNpc2NvIERvbWluZ3VleiIsImVtYWlsIjoiZnJhbmNpc2NvMjguZmRAZ21haWwuY29tIiwiZW1haWxWZXJpZmllZCI6dHJ1ZSwiaW1hZ2UiOiJodHRwczovL2xoMy5nb29nbGV1c2VyY29udGVudC5jb20vYS9BQ2c4b2NLOUdoOGFtV3ZPOGhGb09UQWtPb0VKQUQxVTNDNlNHamZXSlNob3N6ZC1nYlBMd1E9czk2LWMiLCJjcmVhdGVkQXQiOiIyMDI1LTA3LTI3VDA4OjE1OjQwLjM2NFoiLCJ1cGRhdGVkQXQiOiIyMDI1LTEyLTI4VDAxOjI0OjQ2LjIzMloiLCJyb2xlIjoidXNlciIsImJhbm5lZCI6bnVsbCwiYmFuUmVhc29uIjpudWxsLCJiYW5FeHBpcmVzIjpudWxsLCJ1c2VybmFtZSI6bnVsbCwiZGlzcGxheVVzZXJuYW1lIjpudWxsLCJpZCI6IllYN1ZYdkU1S3F1SHB2dEEzZnZtaXUifX0sImV4cGlyZXNBdCI6MTc2NzE5OTkzODUxMywic2lnbmF0dXJlIjoiYm9iOUxxVUx2bnU5ZFZVanZOWS11aUhIanV4cWVWMXNwVUNWUUdKNjRIOCJ9; ph_phc_CctpNPbhBZGC0L3btesUuhLtbK471mX71zItXmReo64_posthog=%7B%22distinct_id%22%3A%22YX7VXvE5KquHpvtA3fvmiu%22%2C%22%24sesid%22%3A%5B1767199687520%2C%22019b7543-f11b-759e-9ccc-792a67cd6f02%22%2C1767198945561%5D%2C%22%24epp%22%3Atrue%2C%22%24initial_person_info%22%3A%7B%22r%22%3A%22https%3A%2F%2Fgithub.com%2Fsupermemoryai%2Fsupermemory%2Fblob%2F85b97b789da098176e44c9b83e3a60e8c4adbb1c%2Fapps%2Fdocs%2Fsupermemory-mcp%2Fsetup.mdx%22%2C%22u%22%3A%22https%3A%2F%2Fapp.supermemory.ai%2F%22%7D%7D",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
    "Priority": "u=4",
    "Pragma": "no-cache",
    "Cache-Control": "no-cache",
}
payload = {"page":1,"limit":500,"sort":"createdAt","order":"desc","containerTags":["sm_project_ana_prevention"]}

response = requests.post(url, headers=headers, json=payload)

print(f"Status: {response.status_code}")
print(f"Response length: {len(response.text)}")

# Save raw response
with open("memory.json", "w", encoding="utf-8") as f:
    f.write(response.text)
print("Saved raw response to memory.json")

# Extract all content fields using ijson


print("\n--- MEMORIES ---")
c = 1
with open('memory.json', 'rb') as f:
    try:
        for prefix, event, value in ijson.parse(f):
            if prefix.endswith('.content') or prefix == 'content':
                print(f"Memory {c}:")
                print(value)
                print()
                c += 1
    except ijson.common.IncompleteJSONError:
        pass  # Stop gracefully when JSON breaks

print(f"Total: {c-1} memories found")
