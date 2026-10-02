from src.formatting import _format_user
from src.models import User


def contact_card(user: User) -> str:
    return _format_user(user)
