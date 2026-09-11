import sys
import time

class timeit:
    """
    A context manager to record the elapsed time of a function.
 
    :param: storage: dict - the storage to record the elapsed time.
    :param: name: str - the name of the function. First entry for a name is stored as a float; subsequent entries promote it to a list of floats.
    :return: None
    """
    def __init__(self, storage, name=None):
        self.storage = storage
        self.name = name if name is not None else sys._getframe(1).f_code.co_name

    def __enter__(self):
        self.start = time.perf_counter() # pylint: disable=attribute-defined-outside-init
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.elapsed = time.perf_counter() - self.start # pylint: disable=attribute-defined-outside-init
        if self.name not in self.storage:
            self.storage[self.name] = self.elapsed
        elif isinstance(self.storage[self.name], list):
            self.storage[self.name].append(self.elapsed)
        else:
            self.storage[self.name] = [self.storage[self.name], self.elapsed]
        return False
