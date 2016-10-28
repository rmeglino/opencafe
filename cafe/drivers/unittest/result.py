from collections import defaultdict
from datetime import datetime
from threading import Lock
from unittest import util
import inspect
import logging
import sys
import traceback2 as traceback

from six.moves import StringIO
import unittest2

from cafe.engine.models.base import BaseModel
from cafe.engine.base import BaseCafeClass

__unittest = True


def synchronized(func):
    lock = Lock()

    def new_func(*args, **kw):
        lock.acquire()
        try:
            return func(*args, **kw)
        finally:
            lock.release()
    return new_func


def sync_class(cls):
    for k, v in vars(cls).items():
        if not k.startswith("_") and inspect.isroutine(cls):
            setattr(cls, k, synchronized(v))
    return cls


class WritelnDecorator(object):
    """Used to decorate file-like objects with a handy 'writeln' method"""
    def __init__(self, stream):
        self.stream = stream

    def __getattr__(self, attr):
        if attr in ('stream', '__getstate__'):
            raise AttributeError(attr)
        return getattr(self.stream, attr)

    def writeln(self, arg=None):
        arg = "" if arg is None else arg
        self.write("{0}\n".format(arg))


class TEST_STATUSES(object):
    ERROR = "ERROR"
    EXPECTED_FAILURE = "expected failure"
    FAILURE = "FAIL"
    SKIP = "skipped"
    SUCCESS = "ok"
    UNEXPECTED_SUCCESS = "unexpected success"


class TestLog(BaseModel):
    def __init__(self):
        self.status = None
        self.start_time = None
        self.stop_time = None
        self.err = ""
        self.subtests = defaultdict(TestLog)
        self.name = ""
        self.description = ""
        self.subtests = []

    @property
    def time(self):
        if self.stop_time is None or self.start_time is None:
            return None
        return (self.stop_time - self.start_time).total_seconds()


@sync_class
class CafeTestResult(BaseCafeClass):
    _previousTestClass = None
    _testRunEntered = False
    _moduleSetUpFailed = False

    def __init__(self):
        self.buffer = False
        self.errors = 0
        self.non_test_errors = 0
        self.expectedFailures = 0
        self.failfast = False
        self.failures = 0
        self.name = None
        self.shouldStop = False
        self.skipped = 0
        self.start_time = None
        self.stop_time = None
        self.successes = 0
        self.tb_locals = False
        self.testsRun = 0
        self.unexpectedSuccesses = 0
        self.log_events = []
        self.running_tests = defaultdict(TestLog)
        self.test_logs = []
        self.module_skipped = 0

    @property
    def time(self):
        if self.stop_time is None or self.start_time is None:
            return 0.0
        return (self.stop_time - self.start_time).total_seconds()

    def printErrors(self):
        pass

    def startTest(self, test):
        "Called when the given test is about to be run"
        test_log = self.running_tests[str(test)]
        test_log.start_time = datetime.now()
        test_log.name = str(test)
        self.testsRun += 1

    def startTestRun(self):
        self.start_time = datetime.now()

    def stopTest(self, test):
        test_log = self.running_tests[str(test)]
        if test_log.status is None and test_log.subtests:
            failure = any([
                t.status in [
                    TEST_STATUSES.FAILURE, TEST_STATUSES.UNEXPECTED_SUCCESS]
                for t in test_log.subtests])
            error = any([
                t.status == TEST_STATUSES.ERROR for t in test_log.subtests])
            skipped = any([
                t.status == TEST_STATUSES.SKIP for t in test_log.subtests])
            if error:
                try:
                    raise Exception("At least one subtest errored")
                except:
                    self.addError(test, sys.exc_info())

            elif failure:
                try:
                    raise Exception("At least one subtest failed")
                except:
                    self.addFailure(test, sys.exc_info())
            elif skipped:
                self.addSkip(test, "At least one subtest skipped")

        test_log.stop_time = datetime.now()
        del self.running_tests[str(test)]
        self.test_logs.append(test_log)

    def stopTestRun(self):
        self.stop_time = datetime.now()

    def addError(self, test, err):
        self.errors += 1
        test_log = self.running_tests[str(test)]
        test_log.name = str(test)
        test_log.err = self._exc_info_to_string(err, test)
        test_log.status = TEST_STATUSES.ERROR

    def addNonTestError(self, test, err):
        self.non_test_errors += 1
        test_log = self.running_tests[str(test)]
        test_log.name = str(test)
        test_log.err = self._exc_info_to_string(err, test)
        test_log.status = TEST_STATUSES.ERROR

    def addFailure(self, test, err):
        self.failures += 1
        test_log = self.running_tests[str(test)]
        test_log.name = str(test)
        test_log.err = self._exc_info_to_string(err, test)
        test_log.status = TEST_STATUSES.FAILURE

    def addSubTest(self, test, subtest, err):
        test_log = self.running_tests[str(test)]
        subtest_log = TestLog()
        test_log.subtests.append(subtest_log)
        subtest_log.name = str(subtest)
        if err is not None:
            if issubclass(err[0], test.failureException):
                subtest_log.status = TEST_STATUSES.FAILURE
            else:
                subtest_log.status = TEST_STATUSES.ERROR
            subtest_log.err = self._exc_info_to_string(err, test)
        else:
            subtest_log.status = TEST_STATUSES.SUCCESS

    def addSuccess(self, test):
        self.successes += 1
        test_log = self.running_tests[str(test)]
        test_log.status = TEST_STATUSES.SUCCESS

    def addSkip(self, test, reason):
        if hasattr(test, "test_case"):
            test_log = self.running_tests[str(test.test_case)]
            subtest_log = TestLog()
            test_log.subtests.append(subtest_log)
            subtest_log.status = TEST_STATUSES.SKIP
            subtest_log.name = str(test)
            return
        self.skipped += 1
        test_log = self.running_tests[str(test)]
        test_log.status = TEST_STATUSES.SKIP

    def addModuleSkip(self, test, reason):
        self.module_skipped += 1
        test_log = self.running_tests[str(test)]
        test_log.status = TEST_STATUSES.SKIP

    def addExpectedFailure(self, test, err):
        self.expectedFailures += 1
        test_log = self.running_tests[str(test)]
        test_log.status = TEST_STATUSES.EXPECTED_FAILURE

    def addUnexpectedSuccess(self, test):
        self.unexpectedSuccesses += 1
        test_log = self.running_tests[str(test)]
        test_log.status = TEST_STATUSES.UNEXPECTED_SUCCESS

    def wasSuccessful(self):
        return self.failures == self.errors == self.unexpectedSuccesses == 0

    def stop(self):
        pass

    def _exc_info_to_string(self, err, test=None):
        """Converts a sys.exc_info()-style tuple of values into a string."""
        exctype, value, tb = err
        # Skip test runner traceback levels
        while tb and self._is_relevant_tb_level(tb):
            tb = tb.tb_next

        if test is not None and exctype is test.failureException:
            # Skip assert*() traceback levels
            length = self._count_relevant_tb_levels(tb)
        else:
            length = None
        tb_e = traceback.TracebackException(
            exctype, value, tb, limit=length, capture_locals=self.tb_locals)
        msgLines = list(tb_e.format())
        return ''.join(msgLines)

    def _is_relevant_tb_level(self, tb):
        return '__unittest' in tb.tb_frame.f_globals

    def _count_relevant_tb_levels(self, tb):
        length = 0
        while tb and not self._is_relevant_tb_level(tb):
            length += 1
            tb = tb.tb_next
        return length

    def __repr__(self):
        return (
            "<%s run=%i errors=%i failures=%i>" % (
                util.strclass(self.__class__), self.testsRun, self.errors,
                self.failures))

    def addLogEvents(self, records):
        for record in records:
            if record.exc_info:
                record.msg = "{0}\n{1}".format(
                    record.msg, self._exc_info_to_string(record.exc_info))
                record.exc_info = None
            self.log_events.append(record)


@sync_class
class CafeTextTestResult(CafeTestResult):
    separator1 = u"=" * 70
    separator2 = u"-" * 70

    def __init__(self, stream=None, verbosity=1):
        super(CafeTextTestResult, self).__init__()

        self.stream = stream or StringIO()
        if not hasattr(self.stream, "writeln"):
            self.stream = unittest2.runner._WritelnDecorator(self.stream)
        self.descriptions = verbosity >= 3
        self.dots = verbosity == 1
        self.showAll = verbosity >= 2
        self.verbosity = verbosity

    def addResult(self, result):
        if result is None:
            return
        self.errors += result.errors
        self.expectedFailures += result.expectedFailures
        self.failures += result.failures
        self.skipped += result.skipped
        self.module_skipped += result.module_skipped
        self.successes += result.successes
        self.tb_locals |= result.tb_locals
        self.testsRun += result.testsRun
        self.unexpectedSuccesses += result.unexpectedSuccesses
        self.log_events += result.log_events
        self.test_logs += result.test_log
        self.non_test_errors += result.non_test_errors
        self.running_tests.update(result.running_tests)
        if hasattr(result.stream, "getvalue"):
            value = result.stream.getvalue().strip()
            if value:
                self.stream.writeln(value)

    def startTest(self, test):
        super(CafeTextTestResult, self).startTest(test)
        test_log = self.running_tests[str(test)]
        test_log.description = self.getDescription(test)

    def _printtest(self, test):
        test_log = self.running_tests[str(test)]
        if self.showAll:
            self.stream.write(test_log.description or str(test))
            self.stream.write(" ... ")
            self.stream.flush()

    def addSuccess(self, test):
        super(CafeTextTestResult, self).addSuccess(test)
        if self.showAll:
            self._printtest(test)
            self.stream.writeln(TEST_STATUSES.SUCCESS)
        elif self.dots:
            self.stream.write('.')
            self.stream.flush()

    def addError(self, test, err):
        super(CafeTextTestResult, self).addError(test, err)
        if self.showAll:
            self._printtest(test)
            self.stream.writeln(TEST_STATUSES.ERROR)
        elif self.dots:
            self.stream.write('E')
            self.stream.flush()

    def addFailure(self, test, err):
        super(CafeTextTestResult, self).addFailure(test, err)
        if self.showAll:
            self._printtest(test)
            self.stream.writeln(TEST_STATUSES.FAILURE)
        elif self.dots:
            self.stream.write('F')
            self.stream.flush()

    def addSkip(self, test, reason):
        super(CafeTextTestResult, self).addSkip(test, reason)
        if self.showAll:
            self._printtest(test)
            self.stream.writeln("{0} {1}".format(TEST_STATUSES.SKIP, reason))
        elif self.dots:
            self.stream.write("s")
            self.stream.flush()

    def addModuleSkip(self, test, reason):
        super(CafeTextTestResult, self).addModuleSkip(test, reason)
        if self.showAll:
            self._printtest(test)
            self.stream.writeln("{0} {1}".format(TEST_STATUSES.SKIP, reason))
        elif self.dots:
            self.stream.write("s")
            self.stream.flush()

    def addExpectedFailure(self, test, err):
        super(CafeTextTestResult, self).addExpectedFailure(test, err)
        if self.showAll:
            self._printtest(test)
            self.stream.writeln(TEST_STATUSES.EXPECTED_FAILURE)
        elif self.dots:
            self.stream.write("x")
            self.stream.flush()

    def addUnexpectedSuccess(self, test):
        super(CafeTextTestResult, self).addUnexpectedSuccess(test)
        if self.showAll:
            self._printtest(test)
            self.stream.writeln(TEST_STATUSES.UNEXPECTED_SUCCESS)
        elif self.dots:
            self.stream.write("u")
            self.stream.flush()

    def printErrors(self):
        if self.dots or self.showAll:
            self.stream.writeln()
        self.printErrorList(TEST_STATUSES.ERROR)
        self.printErrorList(TEST_STATUSES.FAILURE)

    def printErrorList(self, status):
        for test in list(self.running_tests.values()) + self.test_logs:
            if test.status == status:
                self.stream.writeln(self.separator1)
                self.stream.writeln(
                    "{0}: {1}".format(status, test.description or test.name))
                self.stream.writeln(self.separator2)
                self.stream.writeln(test.err)
            for subtest in test.subtests:
                if subtest.status == status:
                    self.stream.writeln(self.separator1)
                    self.stream.writeln(
                        "{0}: {1}".format(
                            status, subtest.description or subtest.name))
                    self.stream.writeln(self.separator2)
                    self.stream.writeln(subtest.err)

    def log_result(self):
        """Gets logs records added to test"""
        handlers = logging.getLogger().handlers
        # handlers can be added here to allow for extensible log storage
        for record in self.log_events:
            for handler in handlers:
                handler.emit(record)

    def addSubTest(self, test, subtest, err):
        super(CafeTextTestResult, self).addSubTest(test, subtest, err)
        log = self.running_tests[str(test)].subtests[-1]
        self.stream.writeln("{0} ... {1}".format(log.name, log.status))

    def getDescription(self, test):
        doc_first_line = test.shortDescription()
        if self.descriptions and doc_first_line:
            return '\n'.join((str(test), doc_first_line))
        else:
            return str(test)

    def print_results(self):
        """Prints results summerized in compile_results messages"""
        self.stream.writeln("-" * 70)
        self.stream.writeln("Ran {0} test{1} in {2:.3f}s".format(
            self.testsRun, "s" * bool(self.testsRun - 1), self.time))
        err = "successes={0}".format(self.successes)
        err += " failures={0}".format(self.failures)
        err += " skipped={0}".format(self.skipped)
        err += " errors={0}".format(self.errors)
        err += " expectedFailures={0}".format(self.expectedFailures)
        err += " unexpectedSuccesses={0}".format(self.unexpectedSuccesses)
        err += " class/module errors={0}".format(self.non_test_errors)
        err += " skipped modules={0}".format(self.module_skipped)
        status = "PASSED" if self.wasSuccessful() else "FAILED"
        self.stream.writeln(
            "\n{0}{1}".format(status, " ({})".format(err) * bool(err)))

    def addNonTestError(self, test, err):
        super(CafeTextTestResult, self).addNonTestError(test, err)
        if self.showAll:
            self._printtest(test)
            self.stream.writeln(TEST_STATUSES.ERROR)
        elif self.dots:
            self.stream.write('E')
            self.stream.flush()
