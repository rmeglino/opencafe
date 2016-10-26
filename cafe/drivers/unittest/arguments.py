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

import argparse
import os
import re

from cafe.drivers.base import get_exception_string
from cafe.engine.config import EngineConfig
from cafe.engine.models.data_interfaces import CONFIG_KEY

ENGINE_CONFIG = EngineConfig()


class ConfigAction(argparse.Action):
    """
        Custom action that checks if config exists.
    """
    def __call__(self, parser, namespace, value, option_string=None):
        value = value if value.endswith('.config') else "{0}.config".format(
            value)
        path = os.path.join(ENGINE_CONFIG.config_directory, value)
        if not os.path.exists(path):
            parser.error(
                "Config does not exist: {0}".format(path), "ConfigAction")
        env_name = CONFIG_KEY.format(section_name="ENGINE", key="test_config")
        os.environ[env_name] = value
        setattr(namespace, self.dest, value)


class DataDirectoryAction(argparse.Action):
    """
        Custom action that checks if data-directory exists.
    """
    def __call__(self, parser, namespace, value, option_string=None):
        if not os.path.exists(value):
            parser.error(
                "Data directory does not exist: {0}".format(value),
                "DataDirectoryAction")
        setattr(namespace, self.dest, value)


class InputFileAction(argparse.Action):
    """
        Custom action that checks if file exists.
    """
    def __call__(self, parser, namespace, value, option_string=None):
        if not os.path.exists(value):
            parser.error(
                "File does not exist: {0}".format(value), "InputFileAction")
        setattr(namespace, self.dest, value)


class TagAction(argparse.Action):
    """
        Processes tag option.
    """
    def __call__(self, parser, namespace, values, option_string=None):
        if values[0] == "+":
            values = values[1:]
            setattr(namespace, "all_tags", True)
        else:
            setattr(namespace, "all_tags", False)
        if len(values) < 1:
            parser.error(
                "--tags/-t: expected at least one argument", "TagAction")
        setattr(namespace, self.dest, values)


class RegexAction(argparse.Action):
    """
        Processes regex option.
    """
    def __call__(self, parser, namespace, values, option_string=None):
        regex_list = []
        for regex in values:
            try:
                regex_list.append(re.compile(regex))
            except re.error as exception:
                parser.error(
                    "Invalid regex {0}".format(regex), "RegexAction",
                    exception)
        setattr(namespace, self.dest, regex_list)


class VerboseAction(argparse.Action):
    """
        Custom action that sets VERBOSE environment variable.
    """
    def __call__(self, parser, namespace, value, option_string=None):
        os.environ["VERBOSE"] = "true" if value == 3 else "false"
        setattr(namespace, self.dest, value)


class ArgumentParser(argparse.ArgumentParser):
    """
        Parses all arguments.
    """
    def __init__(self):
        desc = "Open Common Automation Framework Engine"
        usage_string = """
            cafe-runner <config> <testrepos>... [--dry-run]
                [--data-directory=DATA_DIRECTORY] [--result=(json|xml)]
                [--regex-list=REGEX...] [--file] [--tags=TAG...]
                [--result-directory=RESULT_DIRECTORY] [--verbose=VERBOSE]
                [--workers=NUM] [--threads=NUM]
            cafe-runner --help
            """

        super(ArgumentParser, self).__init__(
            usage=usage_string, description=desc)

        self.prog = "Argument Parser"

        self.add_argument(
            "config",
            action=ConfigAction,
            metavar="<config>",
            help="test config.  Looks in the .opencafe/configs directory."
                 "Example: bsl/uk.json")

        self.add_argument(
            "testrepos",
            nargs="*",
            default=[],
            metavar="<testrepo>...",
            help="The name of the packages containing the tests. "
                 "This overrides the value in the engine.config file, as well "
                 "as the CAFE_OPENCAFE_ENGINE_default_test_repo environment "
                 "variable. Example: ubroast.bsl.v2 ubroast.bsl.v1")

        self.add_argument(
            "--dry-run",
            action="store_true",
            help="dry run.  Don't run tests just print them.  Will run data"
                 " generators.")

        self.add_argument(
            "--regex-list", "-d",
            action=RegexAction,
            nargs="+",
            default=[],
            metavar="REGEX",
            help="Filter by regex against dotpath down to test level"
                 "Example: tests.repo.cafe_tests.NoDataGenerator.test_fail"
                 "Example: 'NoDataGenerator\\.*fail'"
                 "Takes in a list and matches on any")

        self.add_argument(
            "--file", "-F",
            metavar="INPUT_FILE",
            type=argparse.FileType("r"),
            nargs="?",
            help="Runs only tests listed in file."
                 "  Can be created by copying --dry-run response\n Format: "
                 "[test_name] (package[.module[.TestCase]][:package.module."
                 "DataGenClass[:json kwargs or args for DataGenClass]]))")

        self.add_argument(
            "--result", "-R",
            choices=["json", "xml", "subunit"],
            help="Generates a specified formatted result file")

        self.add_argument(
            "--result-directory",
            default="./",
            metavar="RESULT_DIRECTORY",
            help="Directory for result file to be stored")

        self.add_argument(
            "--tags", "-t",
            nargs="+",
            action=TagAction,
            default=[],
            metavar="TAG",
            help="""Run only tests that have tags set.
                By default tests that match any of the tags will be returned.
                Sending a "+" as the first tag in the tag list will only
                return the tests that match all the tags.""")

        self.add_argument(
            "--verbose", "-v",
            action=VerboseAction,
            choices=[1, 2, 3],
            default=2,
            type=int,
            help="Set unittest stdout verbosity")

        self.add_argument(
            "--module-workers",
            nargs="?",
            default=1,
            type=int,
            help="Set number of module subprocceses")

        self.add_argument(
            "--class-workers",
            nargs="?",
            default=1,
            type=int,
            help="Set number of class subprocceses")

        self.add_argument(
            "--test-workers",
            nargs="?",
            default=1,
            type=int,
            help="Set number of test subprocceses")

    def error(self, message, method=None, exception=None):
        msg = "\n{0}".format(get_exception_string(
            "Argument Parser", method, message, exception))
        super(ArgumentParser, self).error(msg)

    def parse_args(self, *args, **kwargs):
        args = super(ArgumentParser, self).parse_args(*args, **kwargs)
        if getattr(args, "all_tags", None) is None:
            args.all_tags = False
        return args
