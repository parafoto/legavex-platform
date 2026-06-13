from dataclasses import dataclass


@dataclass
class ParsedCommand:
    name: str
    argument: str = ""


def parse_command(text: str) -> ParsedCommand:
    raw = text.strip()
    if not raw:
        return ParsedCommand(name="empty")
    if not raw.startswith("/"):
        return ParsedCommand(name="intake", argument=raw)

    parts = raw.split(maxsplit=1)
    name = parts[0].lower()
    argument = parts[1].strip() if len(parts) > 1 else ""
    return ParsedCommand(name=name, argument=argument)

