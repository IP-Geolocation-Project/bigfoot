import uuid
import bisect
from typing import Iterator

class RateLimiterQueue:
    """
    A queue that maintains a sorted list of (timestamp, rl_id) and allows efficient insertion and removal.
    """
    def __init__(self):
        self._items = []         # sorted list of (timestamp, rl_id)
        self._index_map = {}     # rl_id -> index in self._items

    def _rebuild_index(self):
        """Rebuild the index map after any modification to self._items."""
        self._index_map = {rl_id: i for i, (_, rl_id) in enumerate(self._items)}

    def push(self, rl_id: uuid.UUID, timestamp: float):
        """
        Add a new item to the queue. .
        Adds the item in sorted order based on timestamp.

        :param: rl_id: uuid.UUID - the identifier for the rate limit entry.
        :param: timestamp: float - the timestamp associated with the entry.
        :raise: KeyError: if rl_id already exists in the queue.
        """
        if rl_id in self._index_map:
            raise KeyError(f"rl_id {rl_id!r} already exists")

        bisect.insort(self._items, (timestamp, rl_id))
        self._rebuild_index()

    def pop(self) -> tuple[uuid.UUID, float]:
        """
        Remove and return the item with the smallest timestamp. 
        
        :return: tuple[uuid.UUID, float] - a tuple of (rl_id, timestamp) for the item with the smallest timestamp.
        :raise: IndexError: if the queue is empty.
        """
        if not self._items:
            raise IndexError("pop from empty queue")
        timestamp, rl_id = self._items.pop(0)
        self._rebuild_index()
        return (rl_id, timestamp)

    def peek_oldest(self) -> tuple[uuid.UUID, float]:
        """
        Return the item with the smallest timestamp without removing it from the queue.
        
        :return: tuple[uuid.UUID, float] - a tuple of (rl_id, timestamp) for the item with the smallest timestamp.
        """
        if not self._items:
            raise IndexError("peek from empty queue")
        timestamp, rl_id = self._items[0]
        return (rl_id, timestamp)

    def peek_newest(self) -> tuple[uuid.UUID, float]:
        """
        Return the item with the largest timestamp without removing it from the queue.
        
        :return: tuple[uuid.UUID, float] - a tuple of (rl_id, timestamp) for the item with the largest timestamp.
        """
        if not self._items:
            raise IndexError("peek from empty queue")
        timestamp, rl_id = self._items[-1]
        return (rl_id, timestamp)

    def peek_second_to_newest(self) -> tuple[uuid.UUID, float]:
        """
        Return the item with the second largest timestamp without removing it from the queue.
        
        :return: tuple[uuid.UUID, float] - a tuple of (rl_id, timestamp) for the item with the second largest timestamp.
        """
        if len(self._items) < 2:
            raise IndexError("not enough items to peek second to newest")
        timestamp, rl_id = self._items[-2]
        return (rl_id, timestamp)
    
    def get_position(self, rl_id: uuid.UUID) -> int:
        """
        Get the position of rl_id in the queue. Position is defined as the index in the sorted list of items.
        
        :param: rl_id: uuid.UUID - the identifier for the rate limit entry.
        :return: int - the index of rl_id in the queue.
        :raise: KeyError: if rl_id is not in the queue.
        """
        if rl_id not in self._index_map:
            raise KeyError(f"rl_id {rl_id!r} not in queue")
        return self._index_map[rl_id]

    def remove(self, rl_id: uuid.UUID):
        """
        Remove the item with the given rl_id from the queue.
        
        :param: rl_id: uuid.UUID - the identifier for the rate limit entry to remove.
        :raise: KeyError: if rl_id is not in the queue.
        """
        if rl_id not in self._index_map:
            raise KeyError(f"rl_id {rl_id!r} not in queue")
        idx = self._index_map[rl_id]
        self._items.pop(idx)
        self._rebuild_index()

    def discard(self, rl_id: uuid.UUID):
        """
        Discard the item with the given rl_Id form the queue.
        If item is not present in the queue, this method just returns.
        If item is present - removes.
        
        :param: rl_id: uuid.UUID - the identified for entry that should be removed.
        """
        if rl_id not in self._index_map:
            return 
        else:
            self.remove(rl_id)

    def update_timestamp(self, rl_id: uuid.UUID, new_timestamp: float):
        """
        Update the timestamp of the item with the given rl_id and maintain the sorted order of the queue.
     
        :param: rl_id: uuid.UUID - the identifier for the rate limit entry to update.
        :param: new_timestamp: float - the new timestamp to associate with the rl_id.
        :raise: KeyError: if rl_id is not in the queue.
        """
        if rl_id not in self._index_map:
            raise KeyError(f"rl_id {rl_id!r} not in queue")
        idx = self._index_map[rl_id]
        self._items.pop(idx)
        bisect.insort(self._items, (new_timestamp, rl_id))
        self._rebuild_index()

    def __len__(self) -> int:
        """
        Return the number of items in the queue.
        
        :return: int - the number of items in the queue.
        """
        return len(self._items) 

    def __bool__(self) -> bool:
        """
        Return True if the queue is not empty.
        
        :return: bool - true if the queue is not empty.
        """
        return len(self._items) > 0

    def __contains__(self, rl_id: uuid.UUID) -> bool:
        """
        Return True if rl_id is in the queue.
        
        :param: rl_id: uuid.UUID - the identifier for the rate limit entry to check.
        :return: bool - true if rl_id is in the queue.
        """
        return rl_id in self._index_map

    def __repr__(self) -> str:
        """
        Return a string representation of the queue.
        
        :return: str - a string representation of the queue.
        """
        items = [(rid, ts) for ts, rid in self._items]
        return f"FIFOMinHeapQueue({items})"

    def __iter__(self) -> Iterator[tuple[uuid.UUID, float]]:
        """
        Iterate over items in timestamp order, yielding (rl_id, timestamp).
        
        :yield: tuple[uuid.UUID, float] - a tuple of (rl_id, timestamp).
        """
        for timestamp, rl_id in self._items:
            yield (rl_id, timestamp)

    def __getitem__(self, index: int) -> tuple[uuid.UUID, float]:
        """
        Get item by index in timestamp order. Returns (rl_id, timestamp).
        
        :param: index: int - the index of the item to get.
        :return: tuple[uuid.UUID, float] - a tuple of (rl_id, timestamp).
        """
        timestamp, rl_id = self._items[index]
        return (rl_id, timestamp)
    