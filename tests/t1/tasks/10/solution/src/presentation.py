from src.models import User


def render_user(user: User) -> str:
    return f"{user.name} — {user.city}"
