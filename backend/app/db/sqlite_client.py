"""数据库客户端（MySQL 连接池 + 线程安全）

注意：文件名 sqlite_client.py 是历史遗留（项目早期用 SQLite，后迁移到 MySQL），
内容与实现均为 MySQL，为兼容现有 import 路径保留此文件名。

启动时会自动创建缺失的数据库和数据表，因此无需手动执行建库脚本。
"""

import datetime
import pymysql
from dbutils.pooled_db import PooledDB
from contextlib import contextmanager

from config.settings import (
    MYSQL_HOST, MYSQL_PORT, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DATABASE,
)
from app.db.migrations import ALL_TABLES


def ensure_database():
    """确保目标数据库存在；不存在则自动创建。

    连接池在构造时就会尝试建连，若库不存在会直接抛
    `(1049, "Unknown database '...'")` 导致整个后端启动失败，
    所以必须在建池之前先确保库存在。
    """
    conn = pymysql.connect(
        host=MYSQL_HOST, port=MYSQL_PORT,
        user=MYSQL_USER, password=MYSQL_PASSWORD,
        charset="utf8mb4", autocommit=True,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"CREATE DATABASE IF NOT EXISTS `{MYSQL_DATABASE}` "
                f"CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
    finally:
        conn.close()


def _convert_sql(sql: str) -> str:
    """将 SQLite 风格的 ? 占位符转换为 pymysql 的 %s"""
    return sql.replace("?", "%s")


def _normalize_row(row: dict | None) -> dict | None:
    """统一把 datetime/date 对象转为字符串，保持与 SQLite 时代一致的返回类型"""
    if not row:
        return None
    out = {}
    for k, v in row.items():
        if isinstance(v, (datetime.datetime, datetime.date)):
            out[k] = v.strftime("%Y-%m-%d %H:%M:%S") if isinstance(v, datetime.datetime) else v.strftime("%Y-%m-%d")
        else:
            out[k] = v
    return out


class MySQLClient:
    """MySQL 连接池管理（线程安全）"""

    def __init__(self):
        # 先确保数据库存在，否则 PooledDB 在构造阶段就会因
        # Unknown database 而失败，整个应用无法启动。
        ensure_database()
        self.pool = PooledDB(
            creator=pymysql,
            maxconnections=10,
            mincached=2,
            maxcached=5,
            blocking=True,
            host=MYSQL_HOST,
            port=MYSQL_PORT,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            database=MYSQL_DATABASE,
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=False,
        )

    @contextmanager
    def cursor(self):
        conn = self.pool.connection()
        cur = conn.cursor()
        try:
            yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()
            conn.close()

    def init_tables(self):
        """初始化所有表"""
        with self.cursor() as cur:
            for name, sql in ALL_TABLES:
                cur.execute(sql)
        self._upgrade_profiles_unique()

    def _upgrade_profiles_unique(self):
        """历史升级（幂等）：profiles 表去重并加唯一约束，防止无限堆积。

        写入端已改为 ON DUPLICATE KEY UPDATE，每个 (user_id, dimension, field)
        只保留一行；此升级负责处理在建约束之前积累的重复数据。
        """
        with self.cursor() as cur:
            cur.execute(
                """SELECT COUNT(*) AS cnt FROM information_schema.statistics
                   WHERE table_schema = DATABASE() AND table_name = 'profiles'
                   AND index_name = 'uq_profile'"""
            )
            if cur.fetchone()["cnt"]:
                return  # 约束已存在
            # 去重：每组只保留最新一行（与读取端 MAX(id) 语义一致）
            cur.execute(
                """DELETE FROM profiles
                   WHERE id NOT IN (
                       SELECT keep_id FROM (
                           SELECT MAX(id) AS keep_id FROM profiles
                           GROUP BY user_id, dimension, field
                       ) t
                   )"""
            )
            try:
                cur.execute(
                    "ALTER TABLE profiles ADD UNIQUE KEY uq_profile (user_id, dimension, field)"
                )
                print("[DB] profiles 表已去重并添加唯一约束 (user_id, dimension, field)")
            except Exception as e:
                print(f"[DB] profiles 唯一约束添加失败（不影响启动）: {e}")

    def execute(self, sql: str, params: tuple = ()):
        with self.cursor() as cur:
            cur.execute(_convert_sql(sql), params)
            return cur.lastrowid

    def fetch_one(self, sql: str, params: tuple = ()) -> dict | None:
        with self.cursor() as cur:
            cur.execute(_convert_sql(sql), params)
            row = cur.fetchone()
            return _normalize_row(dict(row) if row else None)

    def fetch_all(self, sql: str, params: tuple = ()) -> list[dict]:
        with self.cursor() as cur:
            cur.execute(_convert_sql(sql), params)
            return [_normalize_row(dict(row)) for row in cur.fetchall()]


# 全局单例
db = MySQLClient()
