"""
Six symbol-specific teams.
"""

from teams.team import Team

TEAM_DEFS = [
    ("team1", "Team #1 – NQ Desk", "NQ"),
    ("team2", "Team #2 – ES Desk", "ES"),
    ("team3", "Team #3 – YM Desk", "YM"),
    ("team4", "Team #4 – RTY Desk", "RTY"),
    ("team5", "Team #5 – GC Desk", "GC"),
    ("team6", "Team #6 – CL Desk", "CL"),
]


def build_teams() -> list:
    return [Team(tid, name, sym) for tid, name, sym in TEAM_DEFS]


def team_symbols() -> list:
    return [sym for _, _, sym in TEAM_DEFS]
