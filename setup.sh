#!/bin/bash

set -e

echo -e "######################################"
echo -e "# Fetching and patching dependencies #"
echo -e "######################################\n"

if ! [ -d fusepy ]; then
    git clone https://github.com/fusepy/fusepy
    git -C fusepy apply ../patches/fusepy.patch
fi

if ! [ -d fusetree ]; then
    git clone https://github.com/paulo-raca/fusetree
    git -C fusetree apply ../patches/fusetree.patch
fi


echo -e "\n\n######################################"
echo -e "#         Initializing venv          #"
echo -e "######################################\n"
if ! [ -d .venv ]; then
    python3 -m venv .venv
fi

. .venv/bin/activate


echo -e "\n\n######################################"
echo -e "#       Installing dependencies      #"
echo -e "######################################\n"

## Install dependencies
cd fusepy
python setup.py install
cd ..

cd fusetree
python setup.py install
cd ..

pip install git+https://github.com/Garmelon/PFERD@master --upgrade
