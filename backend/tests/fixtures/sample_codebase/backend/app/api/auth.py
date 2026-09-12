from fastapi import APIRouter

router = APIRouter()


@router.post("/auth/login")
def login(username: str, password: str):
    from app.services.auth_service import authenticate
    return authenticate(username, password)
