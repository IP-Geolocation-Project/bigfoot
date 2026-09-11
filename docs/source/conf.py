# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information
import os
import sys
import importlib.metadata

sys.path.insert(0, os.path.abspath("../.."))

project = 'bigfoot'
copyright = '2026, Huseyn Gambarov'
author = 'Huseyn Gambarov'
release = importlib.metadata.version("bigfoot")

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    'sphinx.ext.apidoc',
    'sphinx.ext.autodoc',
    'sphinx.ext.viewcode',
    'sphinx.ext.intersphinx',

]

# Regenerates docs/source/api on every build, so the stubs are never edited by hand.
apidoc_modules = [
    {
        'path': '../../bigfoot',
        'destination': 'api',
        # Generated protobuf modules carry no useful docstrings.
        'exclude_patterns': ['**/ark_daemon_pb2*.py'],
        'max_depth': 4,
        "separate_modules": True, 
        "module_first": True,       # package docstring above the submodule list
        'automodule_options': {
            'members',
            'undoc-members',
            'show-inheritance',
        },
    },
]

autodoc_default_options = {
    'private-members': True,
    "ignore-module-all": True,
}
# templates_path = ['_templates']

autodoc_class_signature = "separated"
autodoc_member_order = "bysource"
autodoc_typehints = "signature"          

# --- name shortening ---
add_module_names = False
toc_object_entries_show_parents = "hide"
modindex_common_prefix = ["bigfoot."]
maximum_signature_line_length = 88         # wraps long signatures
# python_use_unqualified_type_names = True

intersphinx_mapping = {"python": ("https://docs.python.org/3", None)}

exclude_patterns = []

language = 'en'

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = 'furo'
# html_static_path = ['_static']

