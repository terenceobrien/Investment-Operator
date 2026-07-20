from setuptools import setup

setup(
    name="pyfrbus",
    version="1.1.1",
    python_requires=">=3.9",
    install_requires=[
        "pandas>=2.1.0,<3.0.0",
        "scipy",
        "numpy",
        "black",
        "flake8",
        "mypy",
        "typing_extensions",
        "multiprocess",
        "sympy==1.3",  # Necessary to maintain compatibility with symengine expressions
        "symengine",
        "matplotlib",
        "lxml",
        "networkx",
        "sphinx",
        "setuptools",
    ],
    packages=["pyfrbus"],
)
