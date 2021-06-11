Collapse
--------

This is the cleaned up version of an IRC bot I ran for years. How to use it:

* Create a Twitter OAuth app.
* Using the info from that app, copy the example conf file and update it to your liking
* `pip3 install -r requirements.txt`
* install via `setup.py` as normal
* `python -m collapse config.conf` or whatever you named it
* Follow the prompts to authorize your twitter account

Features
--------

Basically, once a Twitter account is linked, tweet links will be converted to text, with expanded
short URLs. You can also tweet via the bot, using the `twit` command. Any URLs to images will be
uploaded as media with the tweet. You can also quote the last thing a nick said, using `quote <nick>`.
The bot also logs who first posted any URL and shames people for sharing the same link again.

It also parses and displays the content from Mastodon post URLs.

Docker
------

Same instructions, but build the image, and when invoking use `docker run` with volume mounts for the
config files. If you're using Docker, you should know how to do this.
