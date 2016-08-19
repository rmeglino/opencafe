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
import inspect
from importlib import import_module


from cafe.engine.base import BaseCafeClass


class RequiredClientNotDefinedError(Exception):
    """Raised when a behavior method call can't find a required client """
    pass


def behavior(*required_clients):
    """Decorator that tags method as a behavior, and optionally adds
    required client objects to an internal attribute.  Causes calls to this
    method to throw RequiredClientNotDefinedError exception if the containing
    class does not have the proper client instances defined.
    """

    def _decorator(func):
        # Unused for now
        setattr(func, '__is_behavior__', True)
        setattr(func, '__required_clients__', [])
        for client in required_clients:
            func.__required_clients__.append(client)

        def _wrap(self, *args, **kwargs):
            available_attributes = vars(self)
            missing_clients = []
            all_requirements_satisfied = True

            if required_clients:
                for required_client in required_clients:
                    required_client_found = False
                    for attr in available_attributes:
                        attribute = getattr(self, attr, None)
                        if isinstance(attribute, required_client):
                            required_client_found = True
                            break

                    all_requirements_satisfied = (
                        all_requirements_satisfied and
                        required_client_found)

                    missing_clients.append(required_client)

                if not all_requirements_satisfied:
                    msg_plurality = ("an instance" if len(missing_clients) <= 1
                                     else "instances")
                    msg = ("Behavior {0} expected {1} of {2} but couldn't"
                           " find one".format(
                               func, msg_plurality, missing_clients))
                    raise RequiredClientNotDefinedError(msg)
            return func(self, *args, **kwargs)
        return _wrap
    return _decorator


class BaseBehavior(BaseCafeClass):
    pass


class BaseIntegrationBehavior(BaseBehavior):
    MAPPING = {}
    func = None

    def __init__(self, *args, **kwargs):
        super(BaseIntegrationBehavior, self).__init__()
        MAPPING = dict(self.MAPPING)
        for k, v in self.MAPPING.items():
            module, class_ = v.rsplit(".", 1)
            try:
                MAPPING[k] = getattr(import_module(module), class_)
            except ImportError as e:
                self._log.error(
                    "Failed import module: {0}, class: {1}, error: {2}".format(
                        module, class_, e))
        for name, class_ in MAPPING.items():
            if not inspect.isclass(class_):
                self._log.error("Failed to set {0}: in {1}".format(
                    name, self.__name__))
                continue
            for obj in list(args) + kwargs.values():
                if inspect.isclass(obj) and obj is class_:
                    setattr(self, name, obj)
                elif isinstance(obj, class_) and obj.__class__ is class_:
                    setattr(self, name, obj)

    def __call__(self, *args, **kwargs):
        return self.func(*args, **kwargs)


def _get_classes(modules, types):
    try:
        iter(modules)
    except:
        modules = [modules]

    try:
        iter(types)
    except:
        types = (types,)

    for module in modules:
        for objname in dir(module):
            obj = getattr(module, objname, None)
            if (inspect.isclass(obj) and
                    issubclass(obj, types) and obj not in types):
                yield obj


def integration_behavior(**kwargs):
    def decorator(func):
        return type(func.__name__, (BaseIntegrationBehavior,), {
            "MAPPING": kwargs, "func": func, "__name__": func.__name__})
    return decorator


def get_integration_behaviors(modules, names=None, *objs, **kwargs):
    objs = list(objs) + kwargs.values()
    behaviors = {}
    for cls in _get_classes(modules, BaseIntegrationBehavior):
        if names is None:
            behaviors[cls.__name__] = cls(*objs)
        elif names is not None and cls.__name__ in names:
            behaviors[cls.__name__] = cls(*objs)
    return type("IntegrationComposite", (object,), behaviors)
