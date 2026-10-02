class TTLCache:
    def __init__(self, ttl_seconds, clock):
        self._ttl = ttl_seconds
        self._clock = clock
        self._entries = {}

    def get_or_load(self, key, loader):
        now = self._clock()
        entry = self._entries.get(key)
        if entry is not None and now <= entry[0]:
            return entry[1]
        value = loader()
        self._entries[key] = (now + self._ttl, value)
        return value
