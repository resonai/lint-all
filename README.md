# Lint-All

Lint-All is a meta-linter tailored for software development with git. It can run any number of linters that adhere to a certain standard format in their output. Lint-All is designed to compare the current branch to the main branch and output lint comments only for lines that were changed in the current branch with respect to the main branch. This behavior can be controlled through flags to check all files or focus on a specific sub-folder.

## Features

 - Run multiple linters.
 - Support for many standard linters: pylint, cpplint, mypy, golint, and more.
 - Only output lint comments for lines changed in the current branch compared to the main branch.
 - Configurable through a YAML file.
 - Control which linters to run and their configurations.
 - Supports excluding paths and ignoring specific issues.
 - Option to include old issues in the report.

## Installation

```bash
pip install "git+https://github.com/resonai/lint-all.git@pip-distribute#subdirectory=lint_all"
```

## Usage

Lint-All is controlled via a YAML configuration file that specifies the linters to be run. An example configuration file can be downloaded from the repository (all_linters.yaml) and adjusted as needed.

### Basic Usage

```bash
lint_all --linters_config path/to/your_linters_config.yaml
```

### Command Line Arguments

 - `--base_path`: The base path to run linters from (recursively). The default is the current directory.
 - `--ref_branch`: Reference branch against which the current branch is compared. Default is `origin/main`.
 - `--check_all_files`: Run linters on all files. If false, runs only on diff from `ref_branch`.
 - `--report_old_issues`: Include old issues in the report. If not set, ignores old issues.
 - `--ignore_uncommitted_or_staged`: Ignore files with uncommitted or staged changes.
 - `--use_git_lfs`: Pull LFS files from git. Requires installing `git-lfs`.
 - `--linters_config`: YAML configuration of all linters to be used.

## Configuration

The configuration file is a YAML file that specifies the linters to be run and their configurations. Here is an example of what the configuration file might look like:

```yaml
 - name: pylint
   cmd: ["pylint"]
   extensions: [".py"]
   use_stderr: false
   run_by_default: true
   ignored_issues:
     - "C0103"
     - "R0913"
   excluded_paths:
     - "tests/"
     - "docs/"
```
Every linter's 'run_by_default' can be overridden in commandline, e.g.:
```bash
lint_all --linters_config path/to/your_linters_config.yaml --nopylint
```

## License

This project is open-sourced at my request under Apache license by [Resonai Ltd](https://www.resonai.com/) even though I no longer work there, because they are nice, generous people.

## Author

Shir Granot Peled - [Linkedin profile](https://www.linkedin.com/in/shirpeled/), [Blog](https://www.shirpeled.com/)

---

Enjoy using Lint-All for cleaner and more maintainable code!
