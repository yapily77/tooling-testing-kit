#!/bin/bash
rm -rf mutants/tests
pytest tests/math_chapters/test_ch07_luck_pillars.py tests/math_chapters/test_ch11_synthesis.py -q -p no:cacheprovider -o addopts=
