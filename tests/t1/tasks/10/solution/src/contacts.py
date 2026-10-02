from src.models import User
from src.presentation import render_user


def contact_card(user: User) -> str:
    return render_user(user)
