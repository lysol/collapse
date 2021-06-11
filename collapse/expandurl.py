import urllib.request, urllib.parse, urllib.error
import sys, os
import shelve
from urllib.parse import urlparse
from collapse.namespacedBrain import NamespacedBrain
from requests_futures.sessions import FuturesSession
import hashlib

def make_result(startUrl, endUrl):
    """coalesce starting, ending urls into a result structure
    
    Args:
        startUrl (str): the input URL
        endUrl (str): the output URL
    
    Returns:
        dict: structure
    """
    return {
        'end_url': endUrl,
        'start_url': startUrl,
        'end_domain_name': urlparse(endUrl).netloc,
        'status': startUrl != endUrl
    }

def _hexurl(url):
    """sha1 a url
    
    Args:
        url (str): the url
    
    Returns:
        str: the hexed url
    """
    h = hashlib.sha1()
    h.update(url)
    return h.hexdigest()

class WrappedFuture:
    """Wrap a request future into a structure to consume elsewhere
    
    Attributes:
        brain (NamespacedBrain): the storage
        future (object): request_futures
        startUrl (str): input URL
    """
    
    def __init__(self, startUrl, future, brain):
        self.brain = brain
        self.future = future
        self.startUrl = startUrl

    def finish(self):
        """finish the request
        
        Returns:
            dict: result from make_result
        """
        try:
            if self.future is False:
                return
            resp = self.future.result()
            print('Finished getting ' + resp.url)
            newUrl = resp.url
            key = 'expanded_' + _hexurl(newUrl)
            self.brain[key] = newUrl
            return make_result(self.startUrl, newUrl)
        except KeyError as e:
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            print((exc_type, fname, exc_tb.tb_lineno))
            print(e)
            return make_result(self.startUrl, self.startUrl)

class ExpandURL:
    """ExpandURL singleton
    
    Attributes:
        brain (NamespacedBrain): storage
        session (FuturesSession): FuturesSession
    """
    
    def __init__(self):
        self.brain = NamespacedBrain()
        self.session = FuturesSession()

    def expand(self, url):
        """expand a URL
        
        Args:
            url (str): input URL
        
        Returns:
            WrappedFuture: WrappedFuture
        """
        print('expanding ' + url)
        try:
            if len(url) > 50:
                self.brain['expanded_' + _hexurl(url)] = url
            future = self.session.head(url, allow_redirects=True)
            return WrappedFuture(url, future, self.brain)
        except (requests.exceptions.RequestException, requests.exceptions.TooManyRedirects) as e:
            exc_type, exc_obj, exc_tb = sys.exc_info()
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            print((exc_type, fname, exc_tb.tb_lineno))
            print(e)
            return False
        
