import os
from setuptools import setup, find_packages
from distutils.core import Command

with open('requirements.txt') as f:
    required = f.read().splitlines()

reqs = []
for ir in required:
    if ir[0:3] == 'git':
        name = ir.split('/')[-1]
        reqs += ['%s @ %s@master' % (name, ir)]
    else:
        reqs += [ir]

os.system('bash get_scripts.sh')

setup(name='SFC-CAE',
      description="A self-adjusting Space-filling curve (variational) convolutional autoencoder for compressing data on unstructured mesh.",
      url='https://github.com/acse-2020/acse2020-acse9-finalreport-acse-jy220',
      author="Imperial College London",
      author_email='jin.yu20@imperial.ac.uk',
      install_requires=reqs,
      test_suite='tests',
      packages=['sfc_cae'])