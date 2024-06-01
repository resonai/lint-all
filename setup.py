from setuptools import setup

setup(
    entry_points={
        "console_scripts": ["mybinary=lintall.lint_all:main"],
    },
    name="lintall",
)
