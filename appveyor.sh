#!/bin/bash

set -e

pacman --noconfirm -S --needed mingw-w64-i686-python3

git clone --depth 1 https://github.com/Alexpux/MINGW-packages
git clone --depth 1 https://github.com/Alexpux/MSYS2-packages
curl -o srcinfo.json -L 'https://github.com/lazka/msys2-web/releases/download/cache/srcinfo.json'

python3 update-srcinfo.py srcinfo.json MINGW-packages MSYS2-packages
