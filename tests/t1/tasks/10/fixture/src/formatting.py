from src.models import User


def _format_user(user: User) -> str:
    return f"{user.name} — {user.city}"
