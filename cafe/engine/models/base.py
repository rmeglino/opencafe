# Copyright 2016 Rackspace
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
from xml.etree import ElementTree as ET
import json
import logging
import re
import six

from cafe.engine.base import BaseCafeClass


def encode(val):
    if isinstance(val, six.binary_type):
        string = val
    elif isinstance(val, six.string_types):
        string = val.encode("UTF-8")
    else:
        string = str(val).encode("UTF-8")
    return string


class BaseModel(BaseCafeClass):
    __REPR_SEPARATOR__ = '\n'

    def __eq__(self, obj):
        try:
            if vars(obj) == vars(self):
                return True
        except:
            pass
        return False

    def __ne__(self, obj):
        return not self.__eq__(obj)

    def __str__(self):
        string = b"<%s object>\n" % (six.b(type(self).__name__))
        for key, val in vars(self).items():
            if isinstance(val, logging.Logger):
                continue
            key = six.b(key)
            string += b"%s = %s\n" % (key, encode(val))
        try:
            return string.decode("UTF-8")
        except:
            self._log.warning("Invalid UTF-8, binary returned from __str__")
            return string

    def __repr__(self):
        return self.__str__()


class AutoMarshallingModel(BaseModel):

    def __init__(self, kwargs=None):
        if kwargs is None:
            return
        for k, v in kwargs.items():
            if k != "self":
                setattr(self, k, v)

    def _obj_to_json(self):
        return json.dumps(self._obj_to_dict())

    def _obj_to_xml(self):
        element = self._obj_to_xml_ele()
        return ET.tostring(element)

    @classmethod
    def _json_to_obj(cls, string):
        data = json.loads(string, strict=False)
        return cls._dict_to_obj(data)

    @classmethod
    def _xml_to_obj(cls, string):
        data = cls._remove_namespaces(ET.fromstring(string))
        return cls._xml_ele_to_obj(data)

    def _obj_to_dict(self):
        raise NotImplemented

    def _obj_to_xml_ele(self):
        raise NotImplemented

    @classmethod
    def _dict_to_obj(cls, string):
        raise NotImplemented

    @classmethod
    def _xml_ele_to_obj(cls, string):
        raise NotImplemented

    @classmethod
    def _remove_namespaces(cls, element):
        for key, value in element.attrib.items():
            if key.startswith("{"):
                element.set(re.sub("{.*}", "", key), value)
                del element.attrib[key]
        element.tag = re.sub("{.*}", "", element.tag)
        for child in element:
            cls._remove_namespaces(child)
        return element

    @staticmethod
    def _get_sub_model(model, format_type="dict"):
        if model is None:
            if format_type == "dict":
                return None
            elif format_type == "xml_ele":
                return ET.Element(None)
            else:
                return None
        if format_type == "dict":
            name = "_obj_to_dict"
        elif format_type == "xml_ele":
            name = "_obj_to_xml_ele"
        else:
            return None
        func = getattr(model, name)
        return func()

    @classmethod
    def _remove_empty_values(cls, data):
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if v not in ([], {}, None)}
        elif isinstance(data, ET.Element):
            data.attrib = cls._remove_empty_values(data.attrib)
            data._children = [
                c for c in data._children if c.tag is not None and (
                    c.attrib, c.text, c._children)]
            return data

    @staticmethod
    def _build_list_model(data, field_name, model):
        """ Expects data to be a dictionary"""
        if data is None:
            raise Exception(
                "expected data to be a dictionary, received None instead")
        if isinstance(data, dict):
            if data.get(field_name) is None:
                raise Exception(
                    "Expected field name {0} was None or non-existent".format(
                        field_name))
            return [model._dict_to_obj(tmp) for tmp in data.get(field_name)]
        elif isinstance(data, list):
            return [model._dict_to_obj(tmp) for tmp in data]
        return [model._xml_ele_to_obj(tmp) for tmp in data.findall(field_name)]

    @staticmethod
    def _build_list(items, element=None):
        if element is None:
            if items is None:
                return []
            return [item._obj_to_dict() for item in items]
        else:
            if items is None:
                return element
            for item in items:
                element.append(item._obj_to_xml_ele())
            return element

    @staticmethod
    def _find(element, tag):
        return None if element is None else element.find(tag)

    def serialize(self, format_type):
        serialize_method = '_obj_to_{0}'.format(format_type)
        return getattr(self, serialize_method)()

    @classmethod
    def deserialize(cls, serialized_str, format_type):
        try:
            deserialize_method = '_{0}_to_obj'.format(format_type)
            model_object = getattr(cls, deserialize_method)(serialized_str)
        except Exception as deserialization_exception:
            cls._log.exception(deserialization_exception)
            try:
                cls._log.debug(
                    u"Deserialization Error: Attempted to deserialize type"
                    u" using type: {0}".format(format_type.decode(
                        encoding='UTF-8', errors='ignore')))
                cls._log.debug(
                    u"Deserialization Error: Unble to deserialize the "
                    u"following:\n{0}".format(serialized_str.decode(
                        encoding='UTF-8', errors='ignore')))
            except Exception as exception:
                cls._log.exception(exception)
                cls._log.debug(
                    "Unable to log information regarding the "
                    "deserialization exception")
            model_object = None
        return model_object

    @staticmethod
    def _string_to_bool(boolean_string):
        """Returns a boolean value of a boolean value string representation
        """
        if boolean_string.lower() == "true":
            return True
        elif boolean_string.lower() == "false":
            return False
        else:
            raise ValueError(
                msg="Passed in boolean string was neither True or False: {0}"
                .format(boolean_string))

    @staticmethod
    def _bool_to_string(value, true_string='true', false_string='false'):
        """Returns a string representation of a boolean value, or the value
        provided if the value is not an instance of bool
        """

        if isinstance(value, bool):
            return true_string if value is True else false_string
        return value

    @classmethod
    def _replace_dict_key(cls, dictionary, old_key, new_key, recursion=False):
        """Replaces key names in a dictionary, by default only first level keys
        will be replaced, recursion needs to be set to True for replacing keys
        in nested dicts and/or lists
        """
        if old_key in dictionary:
            dictionary[new_key] = dictionary.pop(old_key)

        # Recursion for nested dicts and lists if flag set to True
        if recursion:
            for key, value in dictionary.items():
                if isinstance(value, dict):
                    cls._replace_dict_key(
                        value, old_key, new_key, recursion=True)
                elif isinstance(value, list):
                    dictionaries = (
                        item for item in value if isinstance(item, dict))
                    for x in dictionaries:
                        cls._replace_dict_key(
                            x, old_key, new_key, recursion=True)
        return dictionary


class AutoMarshallingListModel(list, AutoMarshallingModel):
    def __str__(self):
        return list.__str__(self)


class AutoMarshallingDictModel(dict, AutoMarshallingModel):
    def __str__(self):
        return dict.__str__(self)
