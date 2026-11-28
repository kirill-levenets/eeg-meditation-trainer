"""A graph drawn with no text: what pixel and geometry tests count is its lines alone."""


def bare(graph, *, value_labels: bool = False, timestamps: bool = False):
    """`graph` with its value labels and time marks off, unless kept; returns it."""
    graph._show_value_labels = value_labels
    graph._show_timestamps = timestamps
    return graph
