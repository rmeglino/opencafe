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
import sys

# Support for the alternate dill-based multiprocessing library 'multiprocess'
# as an experimental workaround if you're having pickling errors.
from multiprocess import Process, Queue

from unittest2.case import _CapturingHandler as CapturingHandler
import logging
import os
import time
from collections import defaultdict

from cafe.common.reporting import cclogging
from cafe.drivers.base import ErrorMixin
from cafe.drivers.unittest.arguments import ArgumentParser
from cafe.drivers.unittest.result import CafeTextTestResult
from cafe.drivers.unittest.suite import OpenCafeUnittestTestSuite
from cafe.drivers.unittest.suite_builder import SuiteBuilder
from cafe.engine.base import BaseCafeClass
from cafe.engine.config import EngineConfig


class UnittestRunner(BaseCafeClass, ErrorMixin):
    """OpenCafe UnittestRunner"""

    def __init__(self):
        self.print_mug()
        self.cl_args = ArgumentParser().parse_args()
        cclogging.init_root_log_handler()
        self.config = EngineConfig()
        self.print_configuration(self.cl_args.testrepos)
        self.datagen_start = time.time()
        self._log.debug("Starting suite_builder")
        self.suite_builder = SuiteBuilder(
            tags=self.cl_args.tags,
            all_tags=self.cl_args.all_tags,
            regex_list=self.cl_args.regex_list)

    def run(self):
        count = 0
        worker_list = []
        to_worker = Queue()
        from_worker = Queue()
        targets = list(self.suite_builder.load_all(
            self.cl_args.testrepos, self.cl_args.file).items())
        print(len(targets))
        if self.cl_args.module_workers <= len(targets):
            module_workers = self.cl_args.module_workers
        else:
            module_workers = len(targets) if len(targets) > 0 else 1
        for _ in range(module_workers):
            proc = Consumer(
                to_worker, from_worker, self.cl_args.verbose,
                self.cl_args.class_workers, self.cl_args.test_workers)
            worker_list.append(proc)
            proc.start()

        for count, (module, tests) in enumerate(targets, 1):
            to_worker.put((module, tests))

        for _ in range(module_workers):
            to_worker.put(None)

        # A second try catch is needed here because queues can cause locking
        # when they go out of scope, especially when termination signals used
        try:
            master_result = CafeTextTestResult(
                stream=sys.stderr, verbosity=self.cl_args.verbose)
            master_result.name = "Runner"
            master_result.startTestRun()
            for _ in range(count):
                result = from_worker.get()
                result.log_result()
                master_result.addResult(result)
            master_result.stopTestRun()
            master_result.printErrors()
            master_result.print_results()
            print("{0}\nDetailed logs: {1}\n{2}".format(
                "=" * 150, self.config.test_log_dir, "-" * 150))
        except KeyboardInterrupt:
            self.error("Runner", "run", "Keyboard Interrupt, exiting...")
            os.killpg(0, 9)
        return bool(not master_result.wasSuccessful())

    @staticmethod
    def print_mug():
        """Prints the cafe mug"""
        print("""
    ( (
     ) )
  .........
  |       |___
  |       |_  |
  |  :-)  |_| |
  |       |___|
  |_______|
=== CAFE Runner ===""")

    def print_configuration(self, repos):
        """Prints the config/logs/repo/data_directory"""
        print("=" * 150)
        print("Percolated Configuration")
        print("-" * 150)
        if repos:
            print("BREWING FROM: ....: {0}".format(repos[0]))
            for repo in repos[1:]:
                print("{0}{1}".format(" " * 20, repo))
        print("ENGINE CONFIG FILE: {0}".format(self.config.config_path))
        print("TEST CONFIG FILE..: {0}".format(self.config.test_config))
        print("DATA DIRECTORY....: {0}".format(self.config.data_directory))
        print("LOG PATH..........: {0}".format(self.config.test_log_dir))
        print("=" * 150)


class Consumer(Process, BaseCafeClass, ErrorMixin):
    """This class runs as a process and does the test running"""

    def __init__(
        self, to_worker, from_worker, verbose, class_workers=1,
            test_workers=1):
        Process.__init__(self)
        self.to_worker = to_worker
        self.from_worker = from_worker
        self.verbose = verbose
        self.class_workers = class_workers
        self.test_workers = test_workers

    def run(self):
        """Starts the worker listening"""
        logger = logging.getLogger('')
        root_log = logging.getLogger()
        [handler.close()for handler in root_log.handlers]
        while True:
            result = CafeTextTestResult(verbosity=self.verbose)
            suite = OpenCafeUnittestTestSuite(
                class_workers=self.class_workers,
                test_workers=self.test_workers)
            data = self.to_worker.get()
            if data is None:
                return
            result.name, target_tests = data
            dic = defaultdict(list)

            for target_test in target_tests:
                for cls, test_case in target_test:
                    dic[cls].append(cls(test_case))
            for cls, test_cases in dic.items():
                sub_suite = OpenCafeUnittestTestSuite()
                sub_suite.addTests(test_cases)
                suite.addTest(sub_suite)
            handler = CapturingHandler()
            logger.handlers = [handler]
            suite(result)
            result.addLogEvents(handler.watcher.records)
            self.from_worker.put(result)


def entry_point():
    """Function setup.py links cafe-runner to"""
    runner = UnittestRunner()
    status_code = runner.run()
    root_log = logging.getLogger()
    [handler.close()for handler in root_log.handlers]
    sys.exit(status_code)
