#!/usr/bin/python
# -*- coding: utf-8 -*-
# Copyright 2023 Resonai Ltd. | by Shir Peled
"""
Wrapper for helm lint that operates on single files
The linter only works on charts, so changed files must be tracked to the chart's
parent directory, and the output needs to be slightly modified, to match the
standard lint format.
"""
from pathlib import Path
import re
import subprocess
import sys
import os

if __name__ == "__main__":
    file_path = sys.argv[1:][0]
    file_name = os.path.basename(file_path)
    found = False
    dir_to_check = None
    for parent in Path(os.path.abspath(file_path)).parents:
        if "Chart.yaml" in os.listdir(parent):
            found = True
            dir_to_check = parent
            break
    if found:
        result = subprocess.run(
            f"helm lint {dir_to_check}".split(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True
        )
        out_lines = result.stdout.decode("utf-8").splitlines() if result.stdout else []
        for l in out_lines:
            if file_name in l:
                pattern = file_name + r":\d+"
                match_line_num = re.search(pattern, l)
                if match_line_num:
                    line_num = int(match_line_num.group()[len(file_name) + 1 :])
                    print(f"{file_path}:{line_num}: {l}", file=sys.stderr)
