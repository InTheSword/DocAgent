from __future__ import annotations

__version__ = "0.12.0"


class Dummy:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    def __call__(self, *args, **kwargs):
        return Dummy(*args, **kwargs)

    def __getattr__(self, name):
        return Dummy

    def __iter__(self):
        return iter(())

    def __bool__(self):
        return False

    @classmethod
    def create(cls, *args, **kwargs):
        return cls(*args, **kwargs)


def __getattr__(name):
    return Dummy
