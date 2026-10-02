from dataclasses import dataclass


@dataclass(frozen=True)
class Item:
    id: str
    name: str
