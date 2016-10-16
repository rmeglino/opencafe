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
try:
    from multiprocess import Process, Queue
    sys.stdout.write(
        "\n\nUtilizing the pathos multiprocess library. "
        "This feature is experimental\n\n")
except:
    from multiprocessing import Process, Queue

from unittest2.case import _CapturingHandler as CapturingHandler
import logging
import os
import time
from collections import defaultdict

from cafe.common.reporting import cclogging
from cafe.common.reporting.reporter import Reporter
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

        for _ in range(self.cl_args.workers):
            proc = Consumer(to_worker, from_worker, self.cl_args.verbose)
            worker_list.append(proc)
            proc.start()

        for count, (module, tests) in enumerate(self.suite_builder.load_all(
                self.cl_args.testrepos, self.cl_args.file).items(), 1):
            to_worker.put((module, tests))

        for _ in range(self.cl_args.workers):
            to_worker.put(None)

        # A second try catch is needed here because queues can cause locking
        # when they go out of scope, especially when termination signals used
        try:
            master_result = CafeTextTestResult(
                stream=sys.stderr, verbosity=self.cl_args.verbose)
            master_result.name = "Runner"
            for _ in range(count):
                result = from_worker.get()
                result.log_result()
                master_result.addResult(result)
            master_result.printErrors()

            tests_run, errors, failures = (
                master_result.testsRun, master_result.errors, master_result.failures)
            #print(tests_run, errors, failures)

        except KeyboardInterrupt:
            self.error("Runner", "run", "Keyboard Interrupt, exiting...")
            os.killpg(0, 9)
        return bool(sum([errors, failures, not tests_run]))

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

    def compile_results(self, run_time, datagen_time, results):
        """Summarizes results and writes results to file if --result used"""
        all_results = []
        result_dict = {"tests": 0, "errors": 0, "failures": 0, "skipped": 0}
        for dic in results:
            result = dic["result"]
            all_results += dic.get("all_results")
            summary = dic.get("summary")
            for key in result_dict:
                result_dict[key] += summary[key]

            if result.stream.getvalue().strip():
                # this line can be replaced to add an extensible stdout/err log
                sys.stderr.write("{0}\n\n".format(
                    result.stream.getvalue().strip()))

        if self.cl_args.result is not None:
            reporter = Reporter(
                execution_time=run_time,
                datagen_time=datagen_time,
                all_results=all_results)
            reporter.generate_report(
                self.cl_args.result, self.cl_args.result_directory)
        return self.print_results(
            run_time=run_time, datagen_time=datagen_time, **result_dict)

    def print_results(self, tests, errors, failures, skipped,
                      run_time, datagen_time):
        """Prints results summerized in compile_results messages"""
        print("{0}".format("-" * 70))
        print("Ran {0} test{1} in {2:.3f}s".format(
            tests, "s" * bool(tests - 1), run_time))
        print("Generated datasets in {0:.3f}s".format(datagen_time))
        print("Total runtime {0:.3f}s".format(run_time + datagen_time))

        results = []
        if failures:
            results.append("failures={0}".format(failures))
        if skipped:
            results.append("skipped={0}".format(skipped))
        if errors:
            results.append("errors={0}".format(errors))

        status = "FAILED" if failures or errors else "PASSED"
        print("\n{} ".format(status), end="\n" * (not bool(results)))
        if results:
            print("({})".format(", ".join(results)))
        print("{0}\nDetailed logs: {1}\n{2}".format(
            "=" * 150, self.config.test_log_dir, "-" * 150))
        return tests, errors, failures


class Consumer(Process, BaseCafeClass, ErrorMixin):
    """This class runs as a process and does the test running"""

    def __init__(self, to_worker, from_worker, verbose):
        Process.__init__(self)
        self.to_worker = to_worker
        self.from_worker = from_worker
        self.verbose = verbose

    def run(self):
        """Starts the worker listening"""
        logger = logging.getLogger('')
        while True:
            result = CafeTextTestResult(verbosity=self.verbose)
            suite = OpenCafeUnittestTestSuite()
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
    try:
        runner = UnittestRunner()
        root_log = logging.getLogger()
        for handler in root_log.handlers:
            handler.close()
        exit(runner.run())
    except KeyboardInterrupt:
        print_exception("Runner", "run", "Keyboard Interrupt, exiting...")
        os.killpg(0, 9)
