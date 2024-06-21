#!/usr/bin/python
# -*- coding: utf-8 -*-
# Copyright 2020 Resonai Ltd. | by Shir Peled
"""
Run linters on the diff from git
"""
import argparse
import importlib.resources as pkg_resources
import re
import sys
import tempfile
from dataclasses import dataclass, field
from os import path
from subprocess import PIPE, check_output, run

import gitdb
import yaml
from git import Repo

from . import __name__ as pkg_name

WHITE = "\u001b[97;1m"
YELLOW = "\u001b[93;1m"
RED = "\u001b[91;1m"
GREEN = "\u001b[92;1m"
CYAN = "\u001b[96;1m"
ENDC = "\u001b[0m"

REQUIRED_PIP = (
  "cpplint,mypy,pyenchant,pylint,types-mock,types-protobuf,"
  "types-redis,types-requests,types-setuptools,types-six,"
  "types-pyyaml"
)

MYPY_IGNORE = ['error: "Type[Flags]" has no attribute', "error: Source file found twice under different module names"]

GLOBAL_FLAGS = argparse.Namespace()


@dataclass
class Linter:
  name: str
  cmd: list[str]
  extensions: list[str]
  use_stderr: bool = False
  run_by_default: bool = True
  ignored_issues: list[str] = field(default_factory=list)
  excluded_paths: list[str] = field(default_factory=list)


def load_linters(filename: str) -> list[Linter]:
  parsed_linters = []
  with open(filename) as stream:
    try:
      parsed_yaml = yaml.safe_load(stream)
      if not parsed_yaml:
        raise ValueError(f"Empty yaml at {filename}")
      for linter_spec in parsed_yaml:
        parsed_linters.append(Linter(**linter_spec))
    except yaml.YAMLError as exc:
      print(f"Could not read linters from {filename}: {exc}")
      raise exc
  return parsed_linters


def git_exists(repo: Repo, commit: str, full_path: str) -> bool:
  """
  Check whether the file exists in the commit
  """
  path_list = full_path.split("/")
  if not path_list:
    return True
  tree = repo.tree(commit)
  if not path_list[0] in tree:
    return False
  for i in range(1, len(path_list)):
    if "/".join(path_list[: i + 1]) not in tree["/".join(path_list[:i])]:
      return False
  return True


def git_modified_and_staged(repo: Repo) -> list[str]:
  """
  Return a list of modified or staged files
  """
  modified = [x.a_path for x in repo.index.diff(None).iter_change_type("M")]
  staged = [x.a_path for x in repo.index.diff("HEAD").iter_change_type("M")]
  return list(set(modified + staged))


def map_line_numbers(file_name: str, repo: Repo) -> tuple[list[int], list[int]]:
  """
  Return a mapping of old lines to new lines and new lines to old lines, where
  -1 indicates there is no such mapping.

  (the old to new mapping is not required at the time this function is created,
  but will hopefully be used to detect improvements)"""

  # 1. Iterate over git diff lines
  lines = repo.git.diff(GLOBAL_FLAGS.ref_branch, file_name).splitlines()
  i = 0
  old_to_new: dict[int, int] = {}
  new_to_old: dict[int, int] = {}
  chunk_header_regex = r"^@@ -\d+,\d+ \+\d+,\d+ .*@@"
  while i < len(lines):
    line = lines[i]
    # if the current line starts a chunk - process it, otherwise skip
    match = re.search(chunk_header_regex, line)
    if match:
      # p_pair is a pair of pointers, the first is the old line number, the
      # second is the new line number. We advance one of them or both as we go
      # along - inserting the induced mapping into the corresponding
      # dictionaries.
      # Their initial values are taken from the chunk header:
      # @@ -<line # file 1>,<line count> +<line # file 2>,<line count> @@
      p_pair = [int(re.search(r"^.*,", c).group()[1:-1]) for c in match.group()[3:-3].split()]  # type: ignore
      i += 1
      while i < len(lines) and not re.search(chunk_header_regex, lines[i]):
        # read line, if it starts with -, advance one counter, if with + advance
        #  the other, if none then advance both
        if lines[i].startswith("-"):
          old_to_new[p_pair[0]] = -1
          p_pair[0] += 1
        elif lines[i].startswith("+"):
          new_to_old[p_pair[1]] = -1
          p_pair[1] += 1
        else:
          old_to_new[p_pair[0]] = p_pair[1]
          new_to_old[p_pair[1]] = p_pair[0]
          p_pair[0] += 1
          p_pair[1] += 1
        i += 1
    else:
      i += 1

    # fill gaps in mapping
    def fill_gaps_from_mapping(mapping, line_count):
      """
      extends a partial mapping by inducing gap so far.
      e.g. a mapping [1->2, 3->5] will be extended  to:
      [1->2, 2->3, 3->5, 4->6, ...]
      """
      list_mapping = [-1] * (line_count + 1)
      gap = 0
      for i in range(1, len(list_mapping)):
        if i in mapping:
          list_mapping[i] = mapping[i]
          gap = mapping[i] - i
        else:
          list_mapping[i] = i + gap
      return list_mapping

    ref_branch = GLOBAL_FLAGS.ref_branch
    old_line_count = (
      len(repo.git.show(f"{ref_branch}:{file_name}").split("\n")) if git_exists(repo, ref_branch, file_name) else 0
    )
    new_line_count = 0
    if path.isfile(file_name):
      with open(file_name, "r", encoding="utf-8") as f:
        new_line_count = sum(1 for _ in f)
    if old_line_count > 0:
      o2n_list = fill_gaps_from_mapping(old_to_new, old_line_count)
    else:
      o2n_list = []
    n2o_list = fill_gaps_from_mapping(new_to_old, new_line_count)
    return o2n_list, n2o_list


def extract_issues_from_linter_output(
    cmd: list[str], env: dict[str, str], file_name: str, use_stderr: bool
) -> list[str]:
  """
  Run linter command and extract stdout or stderr lines that begin with the file
  name.
  """
  output = (
    run(cmd + [file_name], stdout=PIPE, stderr=PIPE, check=False, env=env)
    if env
    else run(cmd + [file_name], stdout=PIPE, stderr=PIPE, check=False)
  )
  output_txt = output.stderr if use_stderr else output.stdout
  return [l for l in output_txt.decode("utf-8").splitlines() if l.startswith(file_name)]


def run_linter_ignore_old_issues(
  cmd: list[str],
  env: dict[str, str],
  file_name: str,
  ref_dir: str,
  new_to_old: list[int],
  old_to_new: list[int],
  use_stderr: bool,
) -> tuple[list[str], list[str]]:
  """
  Runs a linter with a given command line once on the file_name, and then on the
  same file in the ref_dir folder.
  Returns the only_old_issues, only_new_issues tuple.

  Note that the filtering is quite naive, so if the only diff is line number,
  because a new function was added in the middle, the filtering is *not* clever
  enough to discern that no real change has happened.
  """
  ref_file_name = path.join(ref_dir, file_name)
  issues_ref = extract_issues_from_linter_output(cmd=cmd, env=env, file_name=ref_file_name, use_stderr=use_stderr)
  issues_new = extract_issues_from_linter_output(cmd=cmd, env=env, file_name=file_name, use_stderr=use_stderr)
  # filter out issues identical to ones from the reference lint run, or such
  # that the only difference is the line number, and it matches the new-to-old
  # line mapping induced by git diff.
  issues: tuple[list[str], list[str]] = ([], [])

  def is_issue_from_a_in_b(a_issue, a_file_name, b_file_name, b_issues, a_to_b_line_mapping):
    issue_txt = a_issue.replace(a_file_name, b_file_name)
    match_line_num = re.search(r":\d+:", issue_txt)
    match_line_error = re.search(r": error:", issue_txt)
    if match_line_num:
      line_num = a_to_b_line_mapping[int(match_line_num.group()[1:-1])]
      issue_txt = re.sub(r":\d+:", f":{line_num}:", issue_txt, count=1)
      if line_num == -1 or issue_txt not in b_issues:
        return True
    return match_line_error and issue_txt not in b_issues

  old_new_issues = (issues_ref, issues_new)
  old_new_file = (ref_file_name, file_name)
  old_new_mappings = (old_to_new, new_to_old)
  for i in range(2):
    for issue in old_new_issues[i]:
      j = (i + 1) % 2
      if is_issue_from_a_in_b(issue, old_new_file[i], old_new_file[j], old_new_issues[j], old_new_mappings[i]):
        issues[i].append(issue)
  return issues


def lint_file(
  file_name: str, ref_dir: str, new_to_old: list[int], old_to_new: list[int], linter: Linter
) -> tuple[list[str], list[str]]:
  """
  Returns the (only_old, only_new) comments for the given file as given by the linter
  """
  issues: tuple[list[str], list[str]] = ([], [])
  if not old_to_new or GLOBAL_FLAGS.report_old_issues:
    issues = [], extract_issues_from_linter_output(linter.cmd, {}, file_name, use_stderr=linter.use_stderr)
  else:
    issues = run_linter_ignore_old_issues(
      linter.cmd, {}, file_name, ref_dir, new_to_old, old_to_new, use_stderr=linter.use_stderr
    )
  filtered: tuple[list[str], list[str]] = ([], [])
  for i in range(2):
    for issue in issues[i]:
      if not any(ignore_str in issue for ignore_str in linter.ignored_issues):
        filtered[i].append(issue)
  return filtered


def cleanup(repo: Repo, tmp_dir: str) -> None:
  """
  Clean worktree
  """
  if tmp_dir:
    try:
      repo.git.worktree("remove", "--force", tmp_dir)
    except Exception as exc:  # pylint: disable=broad-except
      print(f"Something went wrong in cleanup: {exc}")


def filter_types_and_folders(linters: list[Linter], file_list: list[str], base_path: str) -> list[str]:
  files = []
  for fname in file_list:
    should_append = False
    if fname.startswith(base_path):
      for linter in linters:
        should_append |= fname.endswith(tuple(linter.extensions)) and not fname.startswith(tuple(linter.excluded_paths))
      if should_append:
        files.append(fname)
  return files


def main(linters: list[Linter], base_path: str):
  """
  Meta linter main entry point
  """
  repo = Repo()
  tmp_dir = ""
  try:
    changed_files = []
    if GLOBAL_FLAGS.check_all_files:
      changed_files = [str(x[1].path) for x in repo.index.iter_blobs()]
    else:
      changed_files = [item.a_path for item in repo.index.diff(GLOBAL_FLAGS.ref_branch)]
      if not GLOBAL_FLAGS.ignore_uncommitted_or_staged:
        modified = git_modified_and_staged(repo)
        if len(modified) > 0:
          print(f"{YELLOW}You have uncommitted changes to tracked files.\n" f"{ENDC}")
        changed_files = list(set(changed_files + modified))
      changed_files = [x for x in changed_files if git_exists(repo, repo.head.object.hexsha, x)]
    changed_files = sorted(filter_types_and_folders(linters, changed_files, base_path))
  except gitdb.exc.BadName:
    print(f"{RED}Branch {GLOBAL_FLAGS.ref_branch} not found{ENDC}")
    cleanup(repo, "")  # This does nothing. Left here for future cleanups.
    sys.exit(1)
  if not changed_files:
    print(f"{GREEN}No changed files.{ENDC}")
    sys.exit(0)
  err_count = 0
  fixed_count = 0
  try:
    changed_files_str = "\n".join(changed_files)
    files_str = "files" if len(changed_files) > 1 else "file"
    print(
      f"{WHITE}Running {len(linters)} linters "
      f'({", ".join([x.name for x in linters])}) on '
      f"{len(changed_files)} {files_str} against branch "
      f"{GLOBAL_FLAGS.ref_branch}.{ENDC}:\n{changed_files_str}"
    )
    tmp_dir = ""
    if not GLOBAL_FLAGS.report_old_issues:
      tmp_dir = tempfile.mkdtemp()
      if GLOBAL_FLAGS.use_git_lfs:
        print(f"Init lfs in reference directory at {tmp_dir}...")
        run(["git", "lfs", "install", "--skip-smudge"], cwd=tmp_dir, check=False)
      print(f"{CYAN}Creating reference worktree at {tmp_dir}...{ENDC}")
      repo.git.worktree("add", "--detach", tmp_dir, GLOBAL_FLAGS.ref_branch)
      if GLOBAL_FLAGS.use_git_lfs:
        print("Pulling lfs")
        run(["git", "lfs", "pull"], cwd=tmp_dir, check=False)
    for i, fname in enumerate(changed_files):
      print(f"{YELLOW}Analyzing file {fname} ({i + 1}/{len(changed_files)}):{ENDC}")
      issues: tuple[list[str], list[str]] = ([], [])

      def extend_both(ls, new_ls):
        for i in range(2):
          ls[i].extend(new_ls[i])

      new_to_old: list[int] = []
      old_to_new: list[int] = []
      if not GLOBAL_FLAGS.report_old_issues:
        old_to_new, new_to_old = map_line_numbers(fname, repo)
      for linter in linters:
        if fname.endswith(tuple(linter.extensions)):
          print(f"{YELLOW}Running {linter.name} on {fname}...{ENDC}")
          extend_both(issues, lint_file(fname, tmp_dir, new_to_old, old_to_new, linter))
      err_count += len(issues[1])
      fixed_count += len(issues[0])

      def issue_sort_key(issue: str) -> int:
        r = re.search(r":\d+:", issue)
        if r:
          return int(r.group()[1:-1])
        return -1

      for i in range(2):
        issues[i].sort(key=issue_sort_key)
      if issues[1]:
        print("\n".join(issues[1]))
      else:
        print("no issues")
      if issues[0]:
        print(f"{len(issues[0])} issues fixed")
    # Make cleaneup withstand exceptions etc
    if not GLOBAL_FLAGS.report_old_issues:
      print(f"{CYAN}Removing reference worktree at {tmp_dir}...{ENDC}")
      repo.git.worktree("remove", "--force", tmp_dir)
    print(f"\n{WHITE}Summary: analyzed {len(changed_files)} files:\n" f"{ENDC}{chr(10).join(changed_files)}")
    exit_err = 0  # for future use when used in CI/CD pipeline
    if fixed_count > 0:
      print(f"\n{GREEN}Fixed {fixed_count} issues.{ENDC}")
    if err_count > 0:
      print(f"\n{RED}Found {err_count} issues.{ENDC}")
      exit_err = 1
    else:
      print(f"\n{GREEN}No issues found.{ENDC}")
  except Exception as exc:  # pylint: disable=broad-except
    print(f"Something went wrong in execution: {exc}")
    cleanup(repo, tmp_dir)
    raise exc
  sys.exit(exit_err)


def add_bool_flag(cli_parser: argparse.ArgumentParser, flag_name: str, default_val: bool, help_str: str):
  feature_parser = cli_parser.add_mutually_exclusive_group(required=False)
  feature_parser.add_argument(f"--{flag_name}", dest=f"{flag_name}", action="store_true", help=help_str)
  feature_parser.add_argument(f"--no{flag_name}", dest=f"{flag_name}", action="store_false")
  cli_parser.set_defaults(**{flag_name: default_val})


def parse_args_and_run() -> None:
  parser = argparse.ArgumentParser(description="Multilinter")
  parser.add_argument(
    "--base_path",
    type=str,
    default=".",
    help="The base path to run linters from (recursively). "
         "The default is the current directory.",
  )
  parser.add_argument(
    "--ref_branch",
    type=str,
    default="origin/main",
    help="Reference branch against which the current branch is compared",
  )
  add_bool_flag(
    cli_parser=parser,
    flag_name="check_all_files",
    default_val=False,
    help_str="Run with all files. If false, runs only on diff from ref_branch",
  )
  add_bool_flag(
    cli_parser=parser,
    flag_name="report_old_issues",
    default_val=False,
    help_str="Also include old issues in the report (if not set - ignores old issues).",
  )
  add_bool_flag(
    cli_parser=parser,
    flag_name="ignore_uncommitted_or_staged",
    default_val=False,
    help_str="Ignore files with uncommitted or staged changes.",
  )
  add_bool_flag(
    cli_parser=parser,
    flag_name="use_git_lfs",
    default_val=False,
    help_str="Also pull lfs files from git. Requires installing git-lfs",
  )
  parser.add_argument(
    "--linters_config",
    type=str,
    default="",
    help="YAML configurtaion of all linters that may be used",
  )  
  initial_flags = parser.parse_known_args()[0]
  if not path.isdir(initial_flags.base_path):
    print(f"{RED}Error: base path {initial_flags.base_path} not found{ENDC}")
    sys.exit(1)    
  if not path.isfile(initial_flags.linters_config):
    print(f"{RED}Error: linters config file {initial_flags.linters_config} not found{ENDC}")
    print(f"You can find a sample file at {pkg_resources.files(pkg_name)}/all_linters.yaml")
    sys.exit(1)
  all_linters_parsed = load_linters(initial_flags.linters_config)
  if not all_linters_parsed:
    print(f"{RED}No linters found in {initial_flags.linters_config}{ENDC}")
    sys.exit(1)
  for linter in all_linters_parsed:
    add_bool_flag(cli_parser=parser, flag_name=linter.name, default_val=linter.run_by_default, help_str=f"Run {linter.name}")
  global GLOBAL_FLAGS
  GLOBAL_FLAGS = parser.parse_args()
  used_linters = [linter for linter in all_linters_parsed if vars(GLOBAL_FLAGS)[linter.name]]
  missing_linters = 0
  for linter in used_linters:
    if len(check_output(["whereis", linter.cmd[0]]).decode('utf-8').split()) == 1:
      missing_linters += 1
      print(f"{RED}Linter {linter.name} (cmd={linter.cmd}) declard in "
            f"{initial_flags.linters_config} not found. Please install it{ENDC}")
  if missing_linters > 0:
    print(f"--- {RED}Missing {missing_linters} linters{ENDC}")
    sys.exit(1)      
  main(used_linters, initial_flags.base_path)
