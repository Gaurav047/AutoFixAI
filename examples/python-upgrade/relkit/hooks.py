"""Deploy hooks are plain functions; the runner passes only the arguments a hook asks for."""

import inspect


def required_params(hook) -> list[str]:
    """Names of the parameters a hook must be given (those without a default value)."""
    spec = inspect.getargspec(hook)
    n_optional = len(spec.defaults or ())
    return spec.args[: len(spec.args) - n_optional]


def call_hook(hook, context: dict):
    """Call `hook` with the subset of `context` it declares as required."""
    missing = [p for p in required_params(hook) if p not in context]
    if missing:
        raise KeyError(f"hook {hook.__name__} needs {missing}")
    return hook(**{p: context[p] for p in required_params(hook)})
