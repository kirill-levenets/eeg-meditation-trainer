"""The metrics graphs' line labels: each series' default, and a key's own label when it has none."""
from types import MappingProxyType

# The defaults every metrics graph starts from; a formula line takes its own name over its slot's.
SERIES_NAMES = MappingProxyType({
    "shamatha_score": "Shamatha",
    "meditation_score": "Meditation",
    "distraction": "Distraction",
    "sinking": "Sinking",
    "subtle_distraction": "Subtle Distraction",
    "native_attention": "NS Attention",
    "native_meditation": "NS Meditation",
    "custom_formula": "Custom 1",
    "custom_formula_2": "Custom 2",
    "custom_formula_3": "Custom 3",
    "program_formula": "Program",
    "program_formula_2": "Program 2",
    "program_formula_3": "Program 3",
})


def prettified(key: str) -> str:
    """A series' label when no name is given for it."""
    return key.replace("_score", "").replace("_", " ").title()
