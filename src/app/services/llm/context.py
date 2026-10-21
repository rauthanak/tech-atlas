"""What a model call is for, recorded with its tokens (services/llm/usage):
the kind of run and its id, the technology, and the skills (or recipe) the
call carries. Callers wrap a call in `with_context(...)`; nested contexts add
to the outer one. A context set in one thread doesn't reach a worker thread,
so the code that runs in a worker sets its own, or is wrapped with `carry`."""

from contextlib import contextmanager
from contextvars import ContextVar, copy_context

call_context: ContextVar[dict] = ContextVar("llm_call_context", default={})


@contextmanager
def with_context(**fields):
    """Add these fields (None values are left out) for calls made inside."""
    token = call_context.set({**call_context.get(), **{k: v for k, v in fields.items() if v is not None}})
    try:
        yield
    finally:
        call_context.reset(token)


def carry(fn):
    """`fn` bound to a copy of the current context, to run once in a worker
    thread (one copy per submission: a context can't be entered twice at once)."""
    ctx = copy_context()
    return lambda *args, **kwargs: ctx.run(fn, *args, **kwargs)
