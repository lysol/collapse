import tempfile
import requests
import shutil

class ImageGetter(object):
    """Grabs images to upload to twitter from URLs
    
    Attributes:
        timeout (int): how long to wait for images before giving up
    """
    
    _suffix_types = {
        'image/gif': '.gif',
        'image/png': '.png',
        'image/jpg': '.jpg',
        'image/jpeg': '.jpg'
    }

    def __init__(self, timeout=1.0):
        """constructor
        
        Args:
            timeout (float, optional): length of timeout
        """
        self.timeout = timeout

    def _get_suffix(self, content_type):
        """detect the file type from the Content-Type header
        
        Args:
            content_type (str): Content-Type header
        
        Returns:
            str: the "suffix"
        """
        content_type = content_type.split(';')[0]
        if content_type in self._suffix_types:
            return self._suffix_types[content_type]
        return None

    def get_images(self, text):
        """Parse a text body for images
        
        Args:
            text (str): text body
        
        Returns:
            list: list of image filenames
        """
        out = []
        media = []
        for part in text.split():
            if part.startswith('http:') or part.startswith('https:'):
                res = self.get_image(part)
                if res is not None:
                    media.append(res)
                else:
                    out.append(part)
            else:
                out.append(part)
        return (' '.join(out), media)

    def get_image(self, url):
        """get an image body
        
        Args:
            url (str): link to image
        
        Returns:
            str: filename of image body
        """
        try:
            req = requests.get(url, stream=True, timeout=1.5)
            if req.status_code == 200 and \
                req.headers['content-type'].startswith('image'):
                suffix = self._get_suffix(req.headers['content-type'])
                if suffix is not None:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
                        req.raw.decode_content = True
                        shutil.copyfileobj(req.raw, f)
                        f.close()
                        return f.name
            else:
                return None
        except requests.exceptions.Timeout as e:
            return None
        except requests.exceptions.ConnectionError as e:
            return None
