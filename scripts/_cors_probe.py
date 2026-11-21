import httpx

base = "http://127.0.0.1:8010"
r = httpx.options(
    f"{base}/api/v1/auth/login",
    headers={
        "Origin": "http://localhost:3010",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
    },
)
print("OPTIONS", r.status_code)
print(dict(r.headers))
r2 = httpx.post(
    f"{base}/api/v1/auth/login",
    json={"email": "admin@example.com", "password": "ChangeMeNow!Admin1"},
    headers={"Origin": "http://localhost:3010"},
)
print("POST", r2.status_code, r2.headers.get("access-control-allow-origin"), r2.json().get("role"))
r3 = httpx.options(
    f"{base}/api/v1/auth/login",
    headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST"},
)
print("OPTIONS :3000", r3.status_code, r3.headers.get("access-control-allow-origin"))
