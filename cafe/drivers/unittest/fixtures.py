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

"""
@summary: Base Classes for Test Fixtures
@note: Corresponds DIRECTLY TO A unittest.TestCase
@see: http://docs.python.org/library/unittest.html#unittest.TestCase
"""
import unittest2

from cafe.engine.base import BaseCafeClass, deprecate, classproperty
from cafe.drivers.unittest.result import CafeTextTestResult


class BaseTestFixture(unittest2.TestCase, BaseCafeClass):
    @classproperty
    def _class_cleanup_tasks(cls):
        if not hasattr(cls, "_class_cleanup_tasks"):
            cls.___class_cleanup_tasks = []
        return cls.___class_cleanup_tasks

    def defaultTestResult(self):
        return CafeTextTestResult()

    @classmethod
    def assertClassSetupFailure(cls, message):
        raise AssertionError("FATAL: %s:%s" % (cls.__name__, message))

    @classmethod
    def assertClassTeardownFailure(cls, message):
        raise AssertionError("FATAL: %s:%s" % (cls.__name__, message))

    @classmethod
    def setUpClass(cls):
        super(BaseTestFixture, cls).setUpClass()
        cls.fixture_log = deprecate(cls._log, "_log", "fixture_log")

    @classmethod
    def _do_class_cleanup_tasks(cls):
        """@summary: Runs class cleanup tasks added during testing"""
        for func, args, kwargs in reversed(cls._class_cleanup_tasks):
            cls._log.debug(
                "Running class cleanup task: %s(%s, %s)",
                func.__name__,
                ", ".join([str(arg) for arg in args]),
                ", ".join(["{0}={1}".format(
                    str(k), str(kwargs[k])) for k in kwargs]))
            try:
                func(*args, **kwargs)
            except Exception as exception:
                # Pretty prints method signature in the following format:
                # "classTearDown failure: Unable to execute FnName(a, b, c=42)"
                cls._log.exception(exception)
                cls._log.error(
                    "classTearDown failure: Exception occured while trying to"
                    " execute class teardown task: %s(%s, %s)",
                    func.__name__,
                    ", ".join([str(arg) for arg in args]),
                    ", ".join(["{0}={1}".format(
                        str(k), str(kwargs[k])) for k in kwargs]))

    @classmethod
    def addClassCleanup(cls, function, *args, **kwargs):
        cls._class_cleanup_tasks.append((function, args or [], kwargs or {}))

    def run(self, result=None):
        orig_result = result
        if result is None:
            result = self.defaultTestResult()
            startTestRun = getattr(result, 'startTestRun', None)
            if startTestRun is not None:
                startTestRun()

        result.startTest(self)

        testMethod = getattr(self, self._testMethodName)
        if (getattr(self.__class__, "__unittest_skip__", False) or
                getattr(testMethod, "__unittest_skip__", False)):
            # If the class or method was skipped.
            try:
                skip_why = (
                    getattr(self.__class__, '__unittest_skip_why__', '') or
                    getattr(testMethod, '__unittest_skip_why__', ''))
                self._addSkip(result, self, skip_why)
            finally:
                result.stopTest(self)
            return result
        expecting_failure = getattr(testMethod,
                                    "__unittest_expecting_failure__", False)
        outcome = unittest2.case._Outcome(result)
        try:
            self._outcome = outcome

            with outcome.testPartExecutor(self):
                self.setUp()
            if outcome.success:
                outcome.expecting_failure = expecting_failure
                with outcome.testPartExecutor(self, isTest=True):
                    testMethod()
                outcome.expecting_failure = False
                with outcome.testPartExecutor(self):
                    self.tearDown()

            self.doCleanups()
            for test, reason in outcome.skipped:
                self._addSkip(result, test, reason)
            self._feedErrorsToResult(result, outcome.errors)
            if outcome.success:
                if expecting_failure:
                    if outcome.expectedFailure:
                        self._addExpectedFailure(
                            result, outcome.expectedFailure)
                    else:
                        self._addUnexpectedSuccess(result)
                else:
                    result.addSuccess(self)
            return result
        finally:
            result.stopTest(self)
            if orig_result is None:
                stopTestRun = getattr(result, 'stopTestRun', None)
                if stopTestRun is not None:
                    stopTestRun()

            # explicitly break reference cycles:
            # outcome.errors -> frame -> outcome -> outcome.errors
            del outcome.errors[:]
            outcome.expectedFailure = None

            # clear the outcome, no more needed
            self._outcome = None
