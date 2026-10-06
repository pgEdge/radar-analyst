#!/bin/bash
flake8 . --count --ignore F722,W503 --max-line-length=79 \
    --max-complexity=8 --statistics
