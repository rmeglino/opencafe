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

from collections import defaultdict
from inspect import isclass, isroutine
import importlib
import json
import pkgutil
import re
import six
import unittest

from cafe.drivers.base import ErrorMixin
from cafe.drivers.unittest.decorators import (
    TEST_TAGS, DATA_DRIVEN_ATTR, DATA_DRIVEN_TEST_PREFIX, _add_tags)
from cafe.engine.base import BaseCafeClass
from cafe.drivers.unittest.decorators import create_dd_class


class TargetTest(BaseCafeClass, ErrorMixin):
    def __init__(
        self, filters, test_module, test_class=None, dd_module=None,
            dd_class=None, dd_json=None, test_name=None):
        self.filters = filters
        self.test_module = test_module
        self.test_class = test_class
        self.dd_module = dd_module
        self.dd_class = dd_class
        self.dd_json = dd_json
        self.test_name = test_name

    def __eq__(self, obj):
        return all([
            self.filters == obj.filters,
            self.test_module == obj.test_module,
            self.test_class == obj.test_class,
            self.dd_module == obj.dd_module,
            self.dd_class == obj.dd_class,
            self.dd_json == obj.dd_json,
            self.test_name == obj.test_name])

    @property
    def _module(self):
        try:
            return importlib.import_module(self.test_module)
        except Exception as e:
            self.error(
                "Suite Builder", "TargetTest",
                "Failed to import test module: {0}".format(self.test_module),
                exception=e)
            return None

    @property
    def _classes(self):
        if self._module is None:
            return
        if self.test_class is not None:
            cls = getattr(self._module, self.test_class, None)
            if cls is not None:
                if self.dd_class is not None:
                    dd_module = importlib.import_module(self.dd_module)
                    dd_class = getattr(dd_module, self.dd_class, None)
                    if dd_class is None:
                        self.error(
                            "TargetTest", "_classes",
                            "Failed get dd class {0} from {1}".format(
                                self.dd_class, self.dd_module))
                        return
                    datasets = (
                        dd_class(**self.dd_json)
                        if isinstance(self.dd_json, dict) else
                        dd_class(*self.dd_json)
                        if isinstance(self.dd_json, list) else dd_class())
                    for dataset in datasets:
                        class_name = re.sub(
                            "fixture", "", self.test_class.__name__,
                            flags=re.IGNORECASE)
                        dataset.name = "{0}_{1}".format(
                            class_name, dataset.name)
                        yield create_dd_class(cls, dataset)

                else:
                    yield cls
            else:
                self.error(
                    "TargetTest", "_classes",
                    "Failed get test class {0} from {1}".format(
                        self.test_class, self.test_module))
        else:
            for name in dir(self._module):
                obj = getattr(self._module, name, None)
                if (isclass(obj) and issubclass(obj, unittest.TestCase) and
                        "fixture" not in obj.__name__.lower()):
                    yield obj

    def _get_class(self, cls, dataset_lists):
        dataset_lists = dataset_lists or getattr(cls, DATA_DRIVEN_ATTR, [])
        for dataset_list in dataset_lists:
            for dataset in dataset_list:
                yield self.create_dd_class(cls, dataset)

    def __iter__(self):
        for cls, test_name in self.get_tests():
            yield cls, test_name

    def get_tests(self):
        for cls in self._classes:
            if self.test_name is not None:
                yield cls, self.test_name
            else:
                for test_name in self.get_tests_from_class(cls):
                    yield cls, test_name

    def get_tests_from_class(self, class_):
        for name in dir(class_):
            if self.check_test(class_, name):
                yield name

    def check_test(self, class_, test_name):
        """Checks filters for a given test, regex/tags"""
        if not test_name.startswith("test_"):
            return False
        dotpath = "{0}.{1}.{2}".format(
            class_.__module__, class_.__name__, test_name)
        test = getattr(class_, test_name, None)
        if test is None:
            return False
        if not isroutine(test):
            return False
        if not self.check_tags(test):
            return False
        return self.check_regex(dotpath)

    def check_regex(self, dotpath):
        return any(
            [bool(r.search(dotpath)) for r in self.filters["regex"]] or [True])

    def check_tags(self, test):
        """
        Checks to see if the test passed in has matching tags.
        if the tags are (foo, bar) this function will match foo or
        bar. if a all_tags is true only tests that contain
        foo and bar will be matched including a test that contains
        (foo, bar, bazz)
        """
        filter_tags = self.filters.get("tags")
        test_tags = getattr(test, TEST_TAGS, [])
        if self.filters.get("all_tags"):
            return all([tag in test_tags for tag in filter_tags])
        else:
            return any([tag in test_tags for tag in filter_tags] or [True])

    @staticmethod
    def create_dd_class(class_, dataset):
        """Creates a class that inherits from the class passed in and contains
        variables from the dataset.  The name is also from the dataset
        """
        if dataset is None:
            return class_
        new_class_name = "{0}_{1}".format(class_.__name__, dataset.name)
        new_class = type(new_class_name, (class_,), dataset.data)
        new_class.__module__ = class_.__module__
        module = importlib.import_module(class_.__module__)
        setattr(module, new_class.__name__, new_class)
        return new_class

    @staticmethod
    def create_dd_func(class_, func, dataset):
        """Creates a function to add to class for ddtests"""
        def new_test(self):
            """Docstring gets replaced by test docstring"""
            dd_test = getattr(self, func.__name__)
            dd_test(**dataset.data)
        base_test_name = func.__name__[len(DATA_DRIVEN_TEST_PREFIX):]
        new_test_name = "{0}_{1}".format(base_test_name, dataset.name)
        new_test.__name__ = new_test_name
        new_test.__doc__ = func.__doc__
        for key, value in vars(func).items():
            if key != DATA_DRIVEN_ATTR:
                setattr(new_test, key, value)
        _add_tags(new_test, dataset.metadata.get('tags', []), TEST_TAGS)
        setattr(class_, new_test_name, new_test)


class SuiteBuilder(BaseCafeClass, ErrorMixin):
    _exit_on_error = True

    def __init__(self, tags=None, all_tags=False, regex_list=None):
        self.filters = {
            "tags": tags or [],
            "all_tags": all_tags,
            "regex": regex_list or []}
        self.modules = set()
        self.packages = set()

    def _populate(self, path):
        path = path.split(".")[0]
        if not path:
            return
        try:
            package = importlib.import_module(path)
        except Exception as e:
            self.error(
                "Suite Builder", "_populate",
                "Failed to import base module: {0}".format(path), e)
            return
        if path in self.packages:
            return
        else:
            self.packages.add(path)
            for _, name, is_pkg in pkgutil.walk_packages(
                    path=package.__path__, prefix="{0}.".format(path)):
                if is_pkg:
                    self.packages.add(name)
                else:
                    self.modules.add(name)

    def load_all(self, testrepos=None, fp=None):
        dic = defaultdict(list)
        testrepos = testrepos or []
        fp = fp or six.moves.StringIO()

        for module, tests in self.load_file(fp).items():
            dic[module] += tests

        for module, tests in self.load_dotpaths(testrepos).items():
            dic[module] += tests
        fp.close()
        return dic

    def load_file(self, fp):
        dic = defaultdict(list)
        for line in fp:
            for test in self.parse_line(line):
                dic[test.test_module].append(test)
        return dic

    def parse_line(self, line):
        rgex = r"^([^\s]+)?\s*\(([^:)\s]+)\s*(:\s*([^:)\s]+)\s*(:\s*(.+))?)?\)"
        match = re.match(rgex, line)
        if match is None:
            self.error(
                "Suite Builder", "parse_line",
                "Failed to parse line: {0}".format(line))
        test_name, test_path, _, dd_path, _, dd_json = match.groups()
        if dd_json is not None:
            try:
                dd_json = json.loads(dd_json)
            except Exception as e:
                self.error(
                    "Suite Builder", "parse_line",
                    "Json error: Line: {0}, json: {0}".format(line, dd_json),
                    exception=e)
        dd_module, dd_class = (
            None, None if dd_path is None else dd_path.rsplit(".", 1))
        test_package, test_module, test_class = self.parse_dotpath(test_path)
        _, dd_module, dd_class = self.parse_dotpath(dd_path)
        if dd_module and not test_class:
            self.error(
                "Suite Builder", "parse_line",
                "dd class required an exact test class: ".format(line))
        if test_module is None:
            for module in [m for m in self.modules if test_package in m and
                           m[len(test_package)] == "."]:
                yield TargetTest(
                    self.filters, test_module=module, test_name=test_name)
        else:
            yield TargetTest(
                self.filters, test_module=test_module, test_class=test_class,
                dd_module=dd_module, dd_class=dd_class, dd_json=dd_json,
                test_name=test_name)

    def parse_dotpath(self, dotpath):
        if dotpath is None:
            return None, None, None
        self._populate(dotpath)
        package = module = cls = None
        if dotpath in self.packages:
            package = dotpath
        elif dotpath in self.modules:
            package = dotpath.rsplit(".", 1)[0]
            module = dotpath
        elif dotpath.rsplit(".", 1)[0] in self.modules:
            package = dotpath.rsplit(".", 2)[0]
            module, cls = dotpath.rsplit(".", 1)
        else:
            self.error(
                "Suite Builder", "parse_dotpath",
                "Failed to validate dotpath: {0}".format(dotpath))
        return package, module, cls

    def load_dotpaths(self, dotpaths):
        dic = defaultdict(list)
        for dotpath in dotpaths:
            for test in self.load_dotpath(dotpath):
                dic[test.test_module].append(test)
        return dic

    def load_dotpath(self, dotpath):
        package, module, cls = self.parse_dotpath(dotpath)
        if module is None:
            for module in [m for m in self.modules if package in m and
                           m[len(package)] == "."]:
                yield TargetTest(self.filters, test_module=module)
        else:
            yield TargetTest(self.filters, test_module=module, test_class=cls)
