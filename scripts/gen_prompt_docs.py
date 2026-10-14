"""Regenerate docs/PROMPTS.md from src/garmin_workouts_mcp/prompts.py.

Run:  python scripts/gen_prompt_docs.py
"""
import inspect
import pathlib

from garmin_workouts_mcp import prompts


class _Capture:
    def __init__(self):
        self.items = []

    def prompt(self, name, description):
        def deco(fn):
            self.items.append((name, description, fn))
            return fn
        return deco


HEADER = """# Ready-made prompts

Prompts for the coaching workflow: a first-run routine for after installing, a weekly
rhythm, and single-purpose checks. They contain no personal data. They tell the assistant
which tools to use to read your real data (so it does not ask for numbers Garmin already
has), and they require your explicit yes before anything is uploaded, scheduled or deleted.

*This file is generated from `src/garmin_workouts_mcp/prompts.py`
(`python scripts/gen_prompt_docs.py`); a Hungarian version is in
[PROMPTS.hu.md](PROMPTS.hu.md).*

## Getting started after installing

1. Install and authenticate the Garmin server (see Setup in the README) and register it in your
   MCP client. Optional: the food diary (README, "Food diary: MyFitnessPal").
2. Restart the client so the tools and prompts load.
3. Run **`first_run_setup`**. It checks the connections, reads your history, asks only what
   Garmin cannot know (goal, available days, equipment, injuries, constraints) and proposes a
   first week. Nothing is written to Garmin before you confirm.
4. Keep what it learns about you in a **private** place, never in a public repository.

A weekly rhythm that works: `weekly_review` on the last day of the week, then
`plan_training_week` for the next one; `recovery_check` on the mornings you doubt a session;
`nutrition_check` when a food diary is connected; `race_prep` once a race is on the calendar.

## How to run them

- In an MCP client that supports prompts they are listed by name (Claude Code shows them as
  slash commands such as `/mcp__garmin-workouts__first_run_setup`). Prompts with arguments
  ask for them.
- Otherwise paste the text below into the chat and fill the values in.

"""


def main():
    cap = _Capture()
    prompts.register_prompts(cap)
    out = [HEADER]
    for name, description, fn in cap.items:
        params = inspect.signature(fn).parameters
        arglist = ", ".join(f"`{p}`" for p in params) or "none"
        body = fn().strip()
        if prompts._RULEBOOK_MARKER in body:
            # The rulebook is long and is shown once, under firefighter_fitness_test_hu.
            head, rest = body.split(prompts._RULEBOOK_MARKER, 1)
            rules = rest.split("\n\nGround rules:", 1)
            body = head.strip() + "\n\n[" + prompts._RULEBOOK_MARKER + "\n the full rulebook text, identical to the one in `firefighter_fitness_test_hu`]"
            if len(rules) == 2:
                body += "\n\nGround rules:" + rules[1]
        out.append(f"## `{name}`\n\n{description}.\n\nArguments: {arglist}\n\n```text\n{body}\n```\n")
    path = pathlib.Path(__file__).resolve().parent.parent / "docs" / "PROMPTS.md"
    path.write_text("\n".join(out), encoding="utf-8")
    print("wrote", path, len(cap.items), "prompts")


if __name__ == "__main__":
    main()
