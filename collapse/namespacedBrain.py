import json
import os
import collections


class NamespacedBrain(dict):
    """NamespacedBrain is flat file store with some basic keyspace segmentation
    to make writes relatively scalable for things like IRC bots. Rather than
    writing the entire file to disk every time there's a write, it's namespaced
    using underscores, which keeps things fairly nimble.
    
    Attributes:
        braindir (str): storage location
        cache (OrderedDict): in-memory cache
        useCache (bool): use an in-memory cache?
    """
    
    def __init__(self, *args, **kwargs):
        """Summary
        
        Args:
            *args: Not used, but passed to dict
            **kwargs: Passed to dict, but also 'braindir', 'useCache' checked
        """
        super(NamespacedBrain, self).__init__(*args, **kwargs)
        if 'braindir' not in kwargs:
            kwargs['braindir'] = os.path.join(os.path.expanduser('~'),
                '.collapseBrain')
        self.braindir = kwargs['braindir']
        if not os.path.exists(self.braindir):
            os.mkdir(self.braindir)
        self.useCache = 'cache' in kwargs and kwargs['cache']
        if self.useCache:
            self.cache = collections.OrderedDict()

    def _keyPrefix(self, key):
        """Get the prefix, if available for a key, to reference as a dir
        
        Args:
            key (str): given keystring
        
        Returns:
            str: The prefix
        """
        if '_' in key:
            part = key.split('_')[0]
            possdir = os.path.join(self.braindir, part)
            if not os.path.exists(possdir):
                os.mkdir(possdir)
            return part
        else:
            return ''

    def _namespace(self, key):
        """auto-namespace a key to use as a prefix
        
        Args:
            key (str): The given key
        
        Returns:
            str: namespaced key
        """
        parts = key.split('_')
        newpart = parts.pop(0)
        return '%s_%s' % (newpart, parts[0][:4])

    def _keyPath(self, key):
        """Retrieve the actual flatfile path for a given key
        
        Args:
            key (str): The given key
        
        Returns:
            str: The path to the storage file for the given key
        """
        return os.path.join(self.braindir, self._keyPrefix(key),
            self._namespace(key))

    def cacheItem(self, key, val):
        """Cache a value
        
        Args:
            key (str): key!
            val (str): value!
        """
        self.cache[key] = val
        if len(self.cache) > 50:
            self.cache.pop(list(self.cache.keys())[-1], None)        

    def __getitem__(self, key):
        """Override __getitem__
        
        Args:
            key (str): key!
        
        Returns:
            str: value!
        
        Raises:
            KeyError: Adhering to dict behavior
        """
        if self.useCache and key in self.cache:
            return self.cache[key]
        fn = self._keyPath(key)
        if not os.path.exists(fn):
            raise KeyError('Key not found')
        val = json.loads(open(fn, 'r').read())[key]
        if self.useCache:
            self.cacheItem(key, val)
        return val

    def __setitem__(self, key, val):
        """__setitem__ implementation
        
        Args:
            key (str): key!
            val (str): value
        """
        fn = self._keyPath(key)
        if os.path.exists(fn):
            contents = json.loads(open(fn, 'r').read())
            contents[key] = val
        else:
            contents = {key: val}
        out = open(fn, 'w')
        out.write(json.dumps(contents))
        out.close()
        if self.useCache:
            self.cacheItem(key, val)

    def __contains__(self, key):
        """__contains__ implementation
        
        Args:
            key (str): key!
        
        Returns:
            bool: if it's contained!
        """
        fn = self._keyPath(key)
        return (self.useCache and key in self.cache) or \
            (os.path.exists(fn) and key in json.loads(open(fn, 'r').read()))

