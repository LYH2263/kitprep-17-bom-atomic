"""测试环境：在导入 app 配置之前把数据库切到临时 sqlite。"""
import os
import tempfile

_fd, _path = tempfile.mkstemp(suffix=".db")
os.environ["DATABASE_URL"] = f"sqlite:///{_path}"
os.environ["SEED_ON_EMPTY"] = "false"
