import json


class RunHistory:
    def __init__(self, history_file: str):
        self.history_file = history_file
        self.entries: list[dict] = []

    @staticmethod
    def lines(text: str | None):
        return None if text is None else text.splitlines()

    def append(self, entry: dict) -> dict:
        self.entries.append(entry)
        return entry

    def last(self) -> dict:
        return self.entries[-1]

    def flush(self) -> None:
        with open(self.history_file, "w") as f:
            json.dump(self.entries, f, indent=4)
