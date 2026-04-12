import requests

url = "http://localhost:8080/api/models"
try:
    response = requests.get(url)
    print("Available Models:", [m["id"] for m in response.json()["data"]])
except Exception as e:
    print("Error:", e)
