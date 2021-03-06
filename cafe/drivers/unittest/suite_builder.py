# Copyright 2015 Rackspace
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from __future__ import print_function

from inspect import isclass, isroutine
import importlib
import json
import pkgutil
import re
import unittest

from cafe.drivers.base import print_exception, get_error
from cafe.drivers.unittest.decorators import PARALLEL_TAGS_LIST_ATTR


class SuiteBuilder(object):
    """Builds suites for OpenCafe Unittest Runner"""
    def __init__(
            self, testrepos, tags=None, all_tags=False, regex_list=None,
            file_=None, exit_on_error=False):
        self.testrepos = testrepos
        self.tags = tags or []
        self.all_tags = all_tags
        self.regex_list = regex_list or []
        self.exit_on_error = exit_on_error
        # dict format {"ubroast.test.test1.TestClass": ["test_t1", "test_t2"]}
        self.file_ = file_ or {}

    def get_suites(self):
        """Creates the suites for testing given the options in init"""
        for tests, class_, dataset in self.load_file():
            yield tests, class_, dataset
        for class_ in self._get_classes(self._get_modules()):
            tests = self._get_tests(class_)
            if tests:
                yield tests, class_, None

    def load_file(self):
        """Load a file generated by --dry_run"""
        for key, tests in self.file_.items():
            test_module, test_class, dd_module, dd_class, dd_args = key
            test_module, test_class = self._import_module(
                test_module, test_class)
            tests = tests or self._get_tests(test_class)
            if test_class is None:
                continue
            if dd_class is not None:
                dd_module, dd_class = self._import_module(dd_module, dd_class)
                if dd_class is None:
                    continue
                arg_data = json.loads(dd_args)
                datasets = (
                    dd_class(**arg_data)if isinstance(arg_data, dict) else
                    dd_class(*arg_data)if isinstance(arg_data, list) else
                    dd_class())
                for dataset in datasets:
                    class_name = re.sub(
                        "fixture", "", test_class.__name__,
                        flags=re.IGNORECASE)
                    dataset.name = "{0}_{1}".format(class_name, dataset.name)
                    yield tests, test_class, dataset
            else:
                yield tests, test_class, None

    def _get_modules(self):
        """Gets modules given the repo paths passed in to init"""
        for repo in self.testrepos:
            if repo.__package__ and repo.__package__ != repo.__name__:
                yield repo
                continue
            prefix = "{0}.".format(repo.__name__)
            for _, modname, is_pkg in pkgutil.walk_packages(
                    path=repo.__path__, prefix=prefix, onerror=lambda x: None):
                if not is_pkg:
                    module = self._import_module(modname)
                    if module is not None:
                        yield module

    @staticmethod
    def _get_classes(modules):
        """Gets classes given a list of modules"""
        for loaded_module in modules:
            for objname in dir(loaded_module):
                obj = getattr(loaded_module, objname, None)
                if (isclass(obj) and issubclass(obj, unittest.TestCase) and
                        "fixture" not in obj.__name__.lower()):
                    yield obj

    def _get_tests(self, class_):
        """Gets tests from a class"""
        tests = []
        for name in dir(class_):
            if name.startswith("test_") and self._check_test(class_, name):
                tests.append(name)
        return tests

    def _check_test(self, class_, test_name):
        """Checks filters for a given test, regex/tags"""
        test = getattr(class_, test_name)
        full_path = "{0}.{1}.{2}".format(
            class_.__module__, class_.__name__, test_name)
        ret_val = isroutine(test) and self._check_tags(test)
        regex_val = not self.regex_list
        for regex in self.regex_list:
            regex_val |= bool(regex.search(full_path))
        return ret_val & regex_val

    def _check_tags(self, test):
        """
        Checks to see if the test passed in has matching tags.
        if the tags are (foo, bar) this function will match foo or
        bar. if a all_tags is true only tests that contain
        foo and bar will be matched including a test that contains
        (foo, bar, bazz)
        """
        test_tags = getattr(test, PARALLEL_TAGS_LIST_ATTR, [])
        if self.all_tags:
            return all([tag in test_tags for tag in self.tags])
        else:
            return any([tag in test_tags for tag in self.tags] or [True])

    def _import_module(self, dot_path, class_name=None):
        class_ = module = None
        try:
            module = importlib.import_module(dot_path)
            if class_name is not None:
                class_ = getattr(module, class_name)
                return module, class_
            else:
                return module
        except Exception as exception:
            print_exception(
                "Suite Builder", "_import_module", dot_path, exception)
            if self.exit_on_error:
                exit(get_error(exception))
        except AttributeError as exception:
            print_exception(
                "Suite Builder", "_import_module", class_name, exception)
            if self.exit_on_error:
                exit(get_error(exception))
        return None, None
