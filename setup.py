#!/usr/bin/env python

from setuptools import setup, find_packages

setup(name='tap-paypal',
      version='0.0.1',
      description='Singer.io tap for extracting data from the Paypal API',
      author='aaron.pugliese@bytecode.io',
      classifiers=['Programming Language :: Python :: 3 :: Only'],
      py_modules=['tap_paypal'],
      install_requires=[
          'singer-python==5.9.0',
          'backoff==1.8.0',
          'requests==2.23.0',
          'pyhumps==1.6.1'
      ],
      extras_require={
          'dev': [
              'pylint',
              'ipdb',
              'nose',
          ]
      },
      python_requires='>=3.6.8',
      entry_points='''
          [console_scripts]
          tap-paypal=tap_paypal:main
      ''',
      packages=find_packages(),
      package_data={
          'tap_paypal': [
              'schemas/*.json',
              'tests/*.py'
          ]
      })
