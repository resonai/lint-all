from setuptools import setup

setup(
    entry_points={
        "console_scripts": ["lint_all=lint_all.lint_all:parse_args_and_run"],
    },
    install_requires=[
        "cpplint",
        "gitdb",
        "GitPython",
        "mypy",
        "pyenchant",
        "pylint",
        "types-mock",
        "types-protobuf",
        "types-redis",
        "types-requests",
        "types-setuptools",
        "types-six",
        "types-pyyaml",
        "pyyaml",
    ],
    name="lint_all",
)
