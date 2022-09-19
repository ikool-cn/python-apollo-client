#!/usr/bin/python
# coding=utf-8

import json
import logging
import os
import threading
from telnetlib import Telnet
from typing import Any, Dict, Optional
import requests
import time
from .exceptions import (BasicException, NameSpaceNotFoundException, ServerNotResponseException)


class ApolloClient(object):
    """
    this module is modified from the project: https://github.com/filamoon/pyapollo
    and had commit the merge request to the original repo
    thanks for the contributors
    """

    def __new__(cls, *args, **kwargs):
        """
        singleton model
        """
        kwargs = {x: kwargs[x] for x in sorted(kwargs)}
        key = repr((args, sorted(kwargs)))
        if hasattr(cls, "_instance"):
            if key not in cls._instance:
                cls._instance[key] = super().__new__(cls)
        else:
            cls._instance = {key: super().__new__(cls)}
        return cls._instance[key]

    def __init__(
            self,
            app_id: str,
            cluster: str = "default",
            config_server_url: str = "http://localhost:8090",
            env: str = "DEV",
            # namespaces: List[str] = None,
            # client_ip: str = None,
            timeout: int = 30,
            sync_time: int = 60,
            cache_file_path: str = None,
            authorization: str = None
            # request_model: Optional[Any] = None,
    ):
        """
        init method
        :param app_id: application id
        :param cluster: cluster name, default value is 'default'
        :param config_server_url: with the format 'http://localhost:8090'
        :param env: environment, default value is 'DEV'
        :param timeout: http request timeout seconds, default value is 30 seconds
        :param ip: the deploy ip for grey release, default value is the local ip
        :param sync_time: the cycle time to update configuration content from server
        :param cache_file_path: local cache file store path
        """
        self.config_server_url = config_server_url
        self.app_id = app_id
        self.cluster = cluster
        self.timeout = timeout
        self.stopped = False
        self._env = env
        # self.client_ip = self.init_client_ip(client_ip)
        remote = self.config_server_url.split(":")
        self.host = f"{remote[0]}:{remote[1]}"
        if len(remote) == 1:
            self.port = 8090
        else:
            self.port = int(remote[2])
        self._authorization = authorization
        self._cache: Dict = {}
        self._notification_map = {}
        self._sync_time = sync_time
        self._hash: Dict = {}
        if cache_file_path is None:
            self._cache_file_path = os.path.join(os.path.abspath(os.path.dirname(__file__)), "config")
        else:
            self._cache_file_path = cache_file_path
        self._path_checker()
        self._read_from_server()

    def _get_clusters(self) -> dict:
        """
        get clusters by app id
        :return :
        """
        url = f"{self.host}:{self.port}/apps/{self.app_id}/clusters"
        r = self._http_get(url)
        if r.status_code == 200:
            return r.json()
        else:
            return {}

    def _get_namespaces(self) -> dict:
        """
        get namespaces by app id and cluster
        :return :
        """
        url = f"{self.host}:{self.port}/apps/{self.app_id}/clusters/{self.cluster}/namespaces"
        r = self._http_get(url)
        if r.status_code == 200:
            namespaces = r.json()
            return {_.get("namespaceName"): _.get("id") for _ in namespaces}
        else:
            return {"application": -1}

    def _get_config_by_namespace(self, namespace: str = "application") -> None:
        """
        get config by namespace
        :param namespace:
        :return:
        """
        url = f"{self.host}:{self.port}/apps/{self.app_id}/clusters/{self.cluster}/namespaces/{namespace}/releases/latest"
        try:
            r = self._http_get(url)
            if r.status_code == 200:
                data = r.json()
                self._cache[namespace] = json.loads(data.get("configurations", "{}"))
                logging.getLogger(__name__).info(
                    "Updated local cache for namespace %s release key %s: %s",
                    namespace,
                    data["releaseKey"],
                    repr(self._cache[namespace]),
                )
                self._update_local_cache(
                    data.get("releaseKey", str(time.time())),
                    data.get("configurations", {}),
                    namespace,
                )
            else:
                logging.getLogger(__name__).info("get configuration from local cache file")
                data = self._get_local_cache_by_namespace(namespace)
                self._cache[namespace] = data

        except BaseException as e:
            logging.getLogger(__name__).warning(str(e))
            data = self._get_local_cache_by_namespace(namespace)
            self._cache[namespace] = data

    # @staticmethod
    # def init_client_ip(client_ip: Optional[str]) -> str:
    #     """
    #     for grey release
    #     :param ip:
    #     :return:
    #     """
    #     if client_ip is None:
    #         try:
    #             import socket
    #
    #             s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    #             s.connect(("8.8.8.8", 53))
    #             client_ip = s.getsockname()[0]
    #             s.close()
    #         except BaseException:
    #             return "127.0.0.1"
    #     return client_ip

    def get_value(self, key: str, default_val: str = None, namespace: str = "application") -> Any:
        """
        get the configuration value
        :param key:
        :param default_val:
        :param namespace:
        :return:
        """
        try:
            # check the namespace is existed or not
            if namespace in self._cache:
                return self._cache[namespace].get(key, default_val)
            return default_val
        except BasicException:
            return default_val

    def start(self) -> None:
        """
        Start the long polling loop.
        :return:
        """
        # check the cache is empty or not
        if len(self._cache) == 0:
            self._read_from_server()
        # start the thread to get config server with schedule
        t = threading.Thread(target=self._long_polling)
        t.setDaemon(True)
        t.start()

    def _http_get(self, url: str, params: Dict = None) -> requests.Response:
        """
        handle http request with get method
        :param url:
        :param params:
        :return:
        """
        try:
            if self._authorization:
                return requests.get(
                    url=url,
                    params=params,
                    timeout=self.timeout // 2,
                    headers={"Authorization": self._authorization},
                )
            else:
                return requests.get(url=url, params=params, timeout=self.timeout // 2)

        except requests.exceptions.ReadTimeout:
            # if read timeout, check the server is alive or not
            try:
                tn = Telnet(host=self.host, port=self.port, timeout=self.timeout // 2)
                tn.close()
                # if connect server succeed, raise the exception that namespace not found
                raise NameSpaceNotFoundException("namespace not found")
            except ConnectionRefusedError:
                # if connection refused, raise server not response error
                raise ServerNotResponseException(
                    "server: %s not response" % self.config_server_url
                )

    def _path_checker(self) -> None:
        """
        create configuration cache file directory if not exits
        :return:
        """
        if not os.path.isdir(self._cache_file_path):
            os.mkdir(self._cache_file_path)

    def _update_local_cache(self, release_key: str, data: str, namespace: str = "application") -> None:
        """
        if local cache file exits, update the content
        if local cache file not exits, create a version
        :param release_key:
        :param data: new configuration content
        :param namespace:
        :return:
        """
        # check the config map release_key, and check it's been updated or not
        if self._hash.get(namespace) != release_key:
            # if it's updated, update the local cache file
            with open(os.path.join(self._cache_file_path, "%s_configuration_%s.txt" % (self.app_id, namespace)), "w") as f:
                f.write(data)
            self._hash[namespace] = release_key

    def _get_local_cache_by_namespace(self, namespace: str = "application") -> Dict:
        """
        get configuration from local cache file
        if local cache file not exits than return empty dict
        :param namespace:
        :return:
        """
        cache_file_path = os.path.join(self._cache_file_path, "%s_configuration_%s.txt" % (self.app_id, namespace))
        if os.path.isfile(cache_file_path):
            with open(cache_file_path, "r") as f:
                result = json.loads(f.readline())
            return result
        return {}

    def _read_from_server(self) -> None:
        """
        read config from remote server
        :return:
        """
        try:
            self._notification_map = self._get_namespaces()
            for namespace in self._notification_map.keys():
                self._get_config_by_namespace(namespace)
        except Exception as e:
            logging.getLogger(__name__).warning(str(e))
            self._read_from_local_cache_file()

    def _read_from_local_cache_file(self) -> bool:
        """
        load all cached files from local path
        is only used while apollo server is unreachable
        :return:
        """
        for file_name in os.listdir(self._cache_file_path):
            file_path = os.path.join(self._cache_file_path, file_name)
            if os.path.isfile(file_path):
                file_simple_name, file_ext_name = os.path.splitext(file_name)
                if file_ext_name == ".swp":
                    continue
                namespace = file_simple_name.split("_")[-1]
                with open(file_path) as f:
                    self._cache[namespace] = json.loads(f.read())
        return True

    def _long_polling(self) -> None:
        """
        long polling for update config
        :return:
        """
        while True:
            logging.getLogger(__name__).info("Entering listener loop...")
            self._read_from_server()
            time.sleep(self._sync_time)
