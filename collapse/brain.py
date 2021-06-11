import json
import os
import collections

class Brain(dict):

    def __init__(self, *args, **kwargs):
        super(Brain, self).__init__(*args, **kwargs)
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
        if '_' in key:
            part = key.split('_')[0]
            possdir = os.path.join(self.braindir, part)
            if not os.path.exists(possdir):
                os.mkdir(possdir)
            return part
        else:
            return ''

    def _keyPath(self, key):
        return os.path.join(self.braindir, self._keyPrefix(key), key)

    def cacheItem(self, key, val):
        self.cache[key] = val
        if len(self.cache) > 50:
            self.cache.pop(list(self.cache.keys())[-1], None)        

    def __getitem__(self, key):
        # print 'getting %s' % key
        if self.useCache and key in self.cache:
            return self.cache[key]
        fn = self._keyPath(key)
        if not os.path.exists(fn):
            raise KeyError('Key not found')
        val = json.loads(open(fn, 'r').read())
        if self.useCache:
            self.cacheItem(key, val)
        return val

    def __setitem__(self, key, val):
        # print 'setting %s' % key
        out = open(self._keyPath(key), 'w')
        out.write(json.dumps(val))
        out.close()
        if self.useCache:
            self.cacheItem(key, val)

    def __contains__(self, key):
        return (self.useCache and key in self.cache) or os.path.exists(self._keyPath(key))

