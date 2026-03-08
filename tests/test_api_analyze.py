import requests
import sys

def test_analyze():
    url = "http://127.0.0.1:5000/api/analyze"
    try:
        resp = requests.post(url, timeout=30)
        print(f"Status Code: {resp.status_code}")
        print(f"Response Body: {resp.text}")
    except Exception as e:
        print(f"Connection failed: {e}")

if __name__ == "__main__":
    test_analyze()
