#!/bin/bash

set -e

git clone https://github.com/msys2/MINGW-packages
git clone https://github.com/msys2/MSYS2-packages
curl -o srcinfo.json -L 'https://github.com/msys2/msys2-web/releases/download/cache/srcinfo.json'

n=0
until [ $n -ge 5 ]
do
   python3 -u update-srcinfo.py srcinfo.json MINGW-packages MSYS2-packages && break || sleep 10
   n=$[$n+1]
done
