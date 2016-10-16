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
from warnings import warn, simplefilter
import inspect
import logging
import re

from cafe.common.reporting import cclogging
from cafe.drivers.unittest.datasets import DatasetList, DSLInstance

DATA_DRIVEN_ATTR = "__data_driven_test_data__"
DATA_DRIVEN_PREFIX = "ddtest_"
TEST_TAGS = "__test_tags__"


class EMPTY_DATASET_ACTIONS(object):
    NONE = "RAISE"
    PRINT = "PRINT"
    RAISE = "NONE"


def _add_tags(func, tags):
    current_tags = getattr(func, TEST_TAGS, set())
    setattr(func, TEST_TAGS, current_tags.union(set(tags)))


def tags(*tags, **attrs):
    def decorator(func):
        _add_tags(func, tags, TEST_TAGS)
        _add_tags(func, ["{0}={1}".format(k, v) for k, v in attrs.items()])
        return func
    return decorator


def data_driven_test(*dataset_sources, **kwargs):
    """Used to define the data source for a data driven test in a
    DataDrivenFixture decorated Unittest TestCase class"""
    def decorator(func):
        """Combines and stores DatasetLists in __data_driven_test_data__"""
        dep_message = "DatasetList object required for data_generator"
        combined_lists = kwargs.get("dataset_source") or DatasetList()
        for key, value in kwargs.items():
            if key != "dataset_source" and isinstance(value, DatasetList):
                value.apply_test_tags(key)
            elif not isinstance(value, (DatasetList, DSLInstance)):
                warn(dep_message, DeprecationWarning)
            combined_lists += value
        for dataset_list in dataset_sources:
            if not isinstance(dataset_list, (DatasetList, DSLInstance)):
                warn(dep_message, DeprecationWarning)
            combined_lists += dataset_list
        setattr(func, DATA_DRIVEN_ATTR, combined_lists)
        return func
    return decorator


def DataDrivenClass(*dataset_lists):
    """Use data driven class decorator. designed to be used on a fixture"""
    def decorator(cls):
        """Creates classes with variables named after datasets.
        Names of classes are equal to (class_name with out fixture) + ds_name
        """
        orig_name = cls.__name__
        if not re.search("fixture", cls.__name__, flags=re.IGNORECASE):
            cls.__name__ = "{0}Fixture".format(orig_name)
        setattr(cls, DATA_DRIVEN_ATTR, dataset_lists)
        return cls
    return decorator


def DataDrivenFixture(cls):
    warn("DataDrivenFixture does nothing", DeprecationWarning)
    return cls


def skip_open_issue(type, bug_id):
    simplefilter('default', DeprecationWarning)
    warn('cafe.drivers.unittest.decorators.skip_open_issue() has been moved '
         'to cafe.drivers.unittest.issue.skip_open_issue()',
         DeprecationWarning)

    try:
        from cafe.drivers.unittest.issue import skip_open_issue as skip_issue
        return skip_issue(type, bug_id)
    except ImportError:
        print('* Skip on issue plugin is not installed. Please install '
              'the plugin to use this functionality')
    return lambda obj: obj


class memoized(object):

    """
    Decorator.
    @see: https://wiki.python.org/moin/PythonDecoratorLibrary#Memoize
    Caches a function's return value each time it is called.
    If called later with the same arguments, the cached value is returned
    (not reevaluated).

    Adds and removes handlers to root log for the duration of the function
    call, or logs return of cached result.
    """

    def __init__(self, func):
        self.func = func
        self.cache = {}
        self.__name__ = func.__name__

    def __call__(self, *args):
        log_name = "{0}.{1}".format(
            cclogging.get_object_namespace(args[0]), self.__name__)

        try:
            hash(args)
        except TypeError:  # unhashable arguments in args
            value = self.func(*args)
            debug = "Uncacheable.  Data returned"
        else:
            if args in self.cache:
                value = self.cache[args]
                debug = "Cached data returned."
            else:
                value = self.cache[args] = self.func(*args)
                debug = "Data cached for future calls"

        self._log_stuff(log_name, debug)
        return value

    def __repr__(self):
        """Return the function's docstring."""
        return self.func.__doc__

    def _log_stuff(self, log_file_name, string):
        log_handler = cclogging.setup_new_cchandler(log_file_name)
        log = logging.getLogger()
        log.addHandler(log_handler)
        try:
            curframe = inspect.currentframe()
            log.debug("{0} called from {1}".format(
                self.__name__, inspect.getouterframes(curframe, 2)[2][3]))
        except:
            log.debug(
                "Unable to log where {0} was called from".format(
                    self.__name__))

        log.debug(string)
        log_handler.close()
        log.removeHandler(log_handler)
