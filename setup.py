import os
from setuptools import setup, find_packages
import distutils
import distutils.command.build
from distutils.core import setup, Extension

setup(name='collapse',
      version='0.0.1',
      description='an irc bot',
      url='http://github.com/lysol/collapse',
      author='Derek Arnold',
      author_email='derek@derekarnold.net',
      license='ISC',
      install_requires=[
          'irc==15.0.5',
          'tweepy',
          'requests',
          'requests-futures',
          'unidecode',
          'Babel',
          'inotify'
          ],
      zip_safe=False,
      packages=find_packages(),
      package_dir={'collapse': 'collapse'},
      package_data={
          'collapse': ['collapse/*.json'],
      },      
      include_package_data=True)
