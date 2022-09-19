# python-apollo-client
A Python Client For Apollo

### 短链接
```python
from pyapollo.apollo_client import ApolloClient

client = ApolloClient(app_id='SampleApp',  config_server_url="http://x.x.x.x:8090", cache_file_path="cache", sync_time = 10, timeout=3)
print(client.get_value("timeout", 30))
```

### 常驻进程,每10秒同步一次服务的最新修改
```python
import time
from pyapollo.apollo_client import ApolloClient

client = ApolloClient(app_id='SampleApp',  config_server_url="http://x.x.x.x:8090", cache_file_path="cache", sync_time = 10, timeout=3)
client.start()

while True:
    print(client.get_value("timeout", 30))
    time.sleep(1)
```