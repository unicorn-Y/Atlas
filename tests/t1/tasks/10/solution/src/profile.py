from src.models import User
from src.presentation import render_user


def profile_label(user: User) -> str:
    return render_user(user)
