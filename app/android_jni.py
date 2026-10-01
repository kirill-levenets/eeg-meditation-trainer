"""pyjnius helpers; jnius is imported inside functions so this module imports off-Android."""


def java_string(text: str):
    """A real java.lang.String: pyjnius resolves a Python str to a char[] overload, and never to CharSequence."""
    from jnius import autoclass

    return autoclass("java.lang.String")(text)
