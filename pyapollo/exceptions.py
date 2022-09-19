#!/usr/bin/python
# coding=utf-8


class BasicException(BaseException):
    def __init__(self, msg: str):
        self._msg = msg
        print(msg)

    def __str__(self):
        return "%s: %s" % (self.__name__, self._msg)


class NameSpaceNotFoundException(BasicException):
    pass


class ServerNotResponseException(BasicException):
    pass
