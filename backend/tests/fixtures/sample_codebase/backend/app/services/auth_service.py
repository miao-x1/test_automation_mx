def authenticate(username: str, password: str) -> dict:
    if username == "alice" and password == "pass123":
        return {"ok": True, "user": username}
    return {"ok": False}


def logout(token: str) -> None:
    return None
