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
Contains a monkeypatched version of unittest's TestSuite class that supports
a version of addCleanup that can be used in classmethods.  This allows a
more granular approach to teardown to be used in setUpClass and classmethod
helper methods
"""
from multiprocess.pool import Pool as _Pool, Process as _Process

from unittest2.suite import TestSuite, _DebugResult, util
import unittest

from cafe.drivers.unittest.result import CafeTextTestResult


class Process(_Process):
    def _get_daemon(self):
        return False

    def _set_daemon(self, value):
        pass
    daemon = property(_get_daemon, _set_daemon)


class Pool(_Pool):
    Process = Process


class OpenCafeUnittestTestSuite(TestSuite):
    def _tearDownPreviousClass(self, test, result):
        currentClass = test.__class__
        if not getattr(currentClass, "_setup_completed", False):
            return
        tearDownClass = getattr(currentClass, 'tearDownClass', None)
        if tearDownClass is not None:
            try:
                tearDownClass()
            except Exception as e:
                if isinstance(result, _DebugResult):
                    raise
                className = util.strclass(currentClass)
                errorName = 'tearDownClass (%s)' % className
                self._addClassOrModuleLevelException(result, e, errorName)
            # Monkeypatch: run class cleanup tasks regardless of whether
            # tearDownClass succeeds or not
            finally:
                if hasattr(currentClass, '_do_class_cleanup_tasks'):
                    currentClass._do_class_cleanup_tasks()

        # Monkeypatch: run class cleanup tasks regardless of whether
        # tearDownClass exists or not
        else:
            if getattr(currentClass, '_do_class_cleanup_tasks', False):
                currentClass._do_class_cleanup_tasks()

    def _handleClassSetUp(self, test, result):
        currentClass = test.__class__
        if result._moduleSetUpFailed:
            return
        if getattr(currentClass, "__unittest_skip__", False):
            return
        currentClass._classSetupFailed = False
        setUpClass = getattr(currentClass, 'setUpClass', None)
        if setUpClass is not None:
            try:
                setUpClass()
                currentClass._setup_completed = True
            except Exception as e:
                if isinstance(result, _DebugResult):
                    raise
                currentClass._classSetupFailed = True
                className = util.strclass(currentClass)
                errorName = 'setUpClass (%s)' % className
                self._addClassOrModuleLevelException(result, e, errorName)
                currentClass._do_class_cleanup_tasks()

    def run(self, result, debug=False):
        result._testRunEntered = True
        suite_list = [s for s in self if issubclass(
            s.__class__, unittest.TestSuite)]
        test_list = [s for s in self if not issubclass(
            s.__class__, unittest.TestSuite)]
        if suite_list:
            self._handleModuleFixture(list(suite_list[0])[0], result)
            result._previousTestClass = list(suite_list[0])[0].__class__
            if getattr(result, '_moduleSetUpFailed', False):
                return result
            pool = Pool(3)
            results = pool.map(
                lambda x: x[0](x[1]), [(suite, CafeTextTestResult(
                    verbosity=result.verbosity)) for suite in suite_list])
            for r in results:
                result.addResult(r)
            self._handleModuleTearDown(result)
        elif test_list:
            self._handleClassSetUp(test_list[0], result)
            result._previousTestClass = test_list[0].__class__
            pool = Pool(3)
            results = pool.map(
                lambda x: x[0](x[1]), [(test, CafeTextTestResult(
                    verbosity=result.verbosity)) for test in test_list])
            for r in results:
                result.addResult(r)
            self._tearDownPreviousClass(test_list[0], result)
        result._testRunEntered = False
        return result
