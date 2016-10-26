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
    TEST_TAGS, DATA_DRIVEN_ATTR, DATA_DRIVEN_PREFIX, _add_tags)
from cafe.engine.base import BaseCafeClass


class TargetTest(BaseCafeClass, ErrorMixin):
    def __init__(
        self, filters, test_module, test_class=None, dd_module=None,
            dd_class=None, dd_json=None, test_name=None):
        self.filters = filters
        self._test_module = test_module
        self._test_class = test_class
        self._dd_module = dd_module
        self._dd_class = dd_class
        self.dd_json = dd_json
        self.test_name = test_name
        self.dd_class
        self.test_class

    @property
    def test_module(self):
        return self.get_module(self._test_module, False, True)

    @property
    def dd_module(self):
        return self.get_module(
            self._dd_module, not self._dd_module, bool(self._dd_module))

    @property
    def dd_class(self):
        return self.get_var(
            self.dd_module, self._dd_class, not self._dd_class,
            bool(self._dd_class))

    @property
    def test_class(self):
        return self.get_var(
            self.test_module, self._test_class, not self._test_class,
            bool(self._test_class))

    def __eq__(self, obj):
        return all([
            self.filters == obj.filters,
            self._test_module == obj._test_module,
            self._test_class == obj._test_class,
            self._dd_module == obj._dd_module,
            self._dd_class == obj._dd_class,
            self.dd_json == obj.dd_json,
            self.test_name == obj.test_name])

    def get_module(self, module, optional=False, exit_on_error=False):
        try:
            return importlib.import_module(module)
        except Exception as e:
            if optional is False:
                self.error(
                    "TargetTest", "get_module",
                    "Failed to import module: {0}".format(module),
                    exception=e, exit_on_error=exit_on_error)

    def get_var(self, obj, var, optional=False, exit_on_error=False):
        try:
            return getattr(obj, var)
        except Exception as e:
            if optional is False:
                self.error(
                    "TargetTest", "get_var",
                    "Failed to get variable {0} from {1}".format(
                        var, str(obj)), exception=e,
                    exit_on_error=exit_on_error)

    def expand_tests(self, cls):
        for var_name in dir(cls):
            if var_name.startswith(DATA_DRIVEN_PREFIX):
                func = self.get_var(cls, var_name)
                dataset_lists = self.get_var(
                    func, DATA_DRIVEN_ATTR, exit_on_error=False)
                for dsl in dataset_lists:
                    success = self.populate_dsl(
                        dsl, var_name, cls, "expand_tests")
                    if success:
                        for dataset in dsl:
                            self.create_dd_func(cls, func, dataset)

    def get_datasets(self, cls):
        if self.dd_class:
            dataset = (
                self.dd_class(**self.dd_json)
                if isinstance(self.dd_json, dict) else
                self.dd_class(*self.dd_json)
                if isinstance(self.dd_json, list) else self.dd_class())
            dataset_lists = [dataset]
        else:
            dataset_lists = self.get_var(cls, DATA_DRIVEN_ATTR, True)
        return dataset_lists

    def populate_dsl(self, dsl, decorated_obj, test_class, calling_func_name):
        try:
            if not list(dsl):
                self.error(
                    "TargetTest", calling_func_name,
                    "DSL {0} empty on {1} in class {2}".format(
                        dsl.__class__.__name__, decorated_obj,
                        test_class.__name__))
            return True
        except Exception as e:
            self.error(
                "TargetTest", calling_func_name,
                "DSL {0} on {1} in class {2} threw exception".format(
                    dsl.__class__.__name__, decorated_obj,
                    test_class.__name__), e)
        return False

    @property
    def classes(self):
        if self.test_module is None:
            return
        if self.test_class:
            classes = [self.test_class]
        else:
            classes = []
            for name in dir(self.test_module):
                obj = self.get_var(self.test_module, name, True)
                if (isclass(obj) and issubclass(obj, unittest.TestCase) and
                        "fixture" not in obj.__name__.lower()):
                    classes.append(obj)
        for class_ in classes:
            dataset_lists = self.get_datasets(class_)
            if dataset_lists is None:
                yield class_
                continue
            for dsl in dataset_lists:
                success = self.populate_dsl(
                    dsl, self.test_class.__name__, self.test_class, "classes")
            if success:
                for dataset in dsl:
                    yield self.create_dd_class(class_, dataset)

    def __iter__(self):
        for cls, test_name in self.get_tests():
            yield cls, test_name

    def get_tests(self):
        for cls in self.classes:
            if self.test_name:
                test = self.get_var(cls, self.test_name, exit_on_error=False)
                if test:
                    yield cls, self.test_name
            else:
                self.expand_tests(cls)
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
        class_name = re.sub(
            "fixture", "", class_.__name__, flags=re.IGNORECASE)
        new_class_name = "{0}_{1}".format(class_name, dataset.name)
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
        new_test_name = "{0}_{1}".format(func.__name__[2:], dataset.name)
        new_test.__name__ = new_test_name
        new_test.__doc__ = func.__doc__
        for key, value in vars(func).items():
            if key != DATA_DRIVEN_ATTR:
                setattr(new_test, key, value)
        _add_tags(new_test, dataset.metadata.get('tags', []))
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
            return False
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
                dic[test._test_module].append(test)
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
        if self._populate(dotpath) is False:
            return None, None, None
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
                dic[test._test_module].append(test)
        return dic

    def load_dotpath(self, dotpath):
        package, module, cls = self.parse_dotpath(dotpath)
        if module is None:
            for module in [m for m in self.modules if package in m and
                           m[len(package)] == "."]:
                yield TargetTest(self.filters, test_module=module)
        else:
            yield TargetTest(self.filters, test_module=module, test_class=cls)
