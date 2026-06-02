from __future__ import annotations

from pathlib import Path

from Cython.Build import cythonize
from setuptools import Extension, setup


ROOT = Path(__file__).resolve().parent
APP_ROOT = ROOT / "app"

EXCLUDED = {
    APP_ROOT / "__init__.py",
    APP_ROOT / "api.py",
    APP_ROOT / "api_routes" / "auth.py",
    APP_ROOT / "worker.py",
    APP_ROOT / "migrate.py",
}


def module_name(path: Path) -> str:
    return ".".join(path.relative_to(ROOT).with_suffix("").parts)


extensions = [
    Extension(module_name(path), [str(path)])
    for path in sorted(APP_ROOT.rglob("*.py"))
    if path not in EXCLUDED and path.name != "__init__.py"
]

setup(
    name="streamtrident-protected",
    ext_modules=cythonize(
        extensions,
        compiler_directives={
            "language_level": "3",
            "binding": True,
            "embedsignature": True,
        },
        annotate=False,
    ),
)
