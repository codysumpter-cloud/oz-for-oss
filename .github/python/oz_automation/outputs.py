from __future__ import annotations

import os


def _write_multiline(path: str, key: str, value: str) -> None:
    delimiter = "__OZ_AUTOMATION_EOF__"
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(f"{key}<<{delimiter}\n{value}\n{delimiter}\n")


def set_output(name: str, value: object) -> None:
    text = "" if value is None else str(value)
    path = os.getenv("GITHUB_OUTPUT")
    if path:
        _write_multiline(path, name, text)
        return
    print(f"{name}={text}")


def append_summary(text: str) -> None:
    path = os.getenv("GITHUB_STEP_SUMMARY")
    if not path:
        print(text)
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(text)
        if not text.endswith("\n"):
            handle.write("\n")
