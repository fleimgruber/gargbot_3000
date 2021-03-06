#! /usr/bin/env python3.6
# coding: utf-8
import datetime as dt
import os
import re
import typing as t
from contextlib import contextmanager
from pathlib import Path
from xml.dom.minidom import parseString

import aiosql
import dropbox
import jinja2
import migra
import psycopg2
from aiosql.adapters.psycopg2 import PsycoPG2Adapter
from PIL import Image
from psycopg2.extensions import connection
from psycopg2.extras import DictCursor
from psycopg2.pool import ThreadedConnectionPool
from sqlbag import S

from gargbot_3000 import config
from gargbot_3000.logger import log


class LoggingCursor(DictCursor):
    def execute(self, query, args=None):
        log.info(query % args if args else query)
        return super().execute(query, args)

    def executemany(self, query, args=None):
        log.info(query % args if args else query)
        return super().executemany(query, args)


credentials = {
    "user": config.db_user,
    "password": config.db_password,
    "host": config.db_host,
    "port": config.db_port,
    "cursor_factory": LoggingCursor,
}


class ConnectionPool:
    """https://gist.github.com/jeorgen/4eea9b9211bafeb18ada"""

    is_setup = False

    def setup(self):
        self.last_seen_process_id = os.getpid()
        self._init()
        self.is_setup = True

    def _init(self):
        self._pool = ThreadedConnectionPool(
            1, 10, database=config.db_name, **credentials
        )

    def _getconn(self) -> connection:
        current_pid = os.getpid()
        if not (current_pid == self.last_seen_process_id):
            self._init()
            log.debug(
                f"New id is {current_pid}, old id was {self.last_seen_process_id}"
            )
            self.last_seen_process_id = current_pid
        conn = self._pool.getconn()
        return conn

    def _putconn(self, conn: connection):
        return self._pool.putconn(conn)

    def closeall(self):
        self._pool.closeall()

    @contextmanager
    def get_connection(self) -> t.Generator[connection, None, None]:
        try:
            conn = self._getconn()
            yield conn
        finally:
            self._putconn(conn)

    @contextmanager
    def get_cursor(self, commit=False) -> t.Generator[LoggingCursor, None, None]:
        with self.get_connection() as conn:
            cursor = conn.cursor(cursor_factory=LoggingCursor)
            try:
                yield cursor
                if commit:
                    conn.commit()
            finally:
                cursor.close()


def connect() -> connection:
    log.info("Connecting to db")
    conn = psycopg2.connect(database=config.db_name, **credentials)
    return conn


class JinjaSqlAdapter(PsycoPG2Adapter):
    jinja_env = jinja2.Environment(
        block_start_string="/*{%",
        block_end_string="%}*/",
        variable_start_string="/*{{",
        variable_end_string="}}*/",
        undefined=jinja2.StrictUndefined,
    )

    @classmethod
    def render_template(cls, sql: str, parameters: dict) -> str:
        template = cls.jinja_env.from_string(sql)
        query = template.render(**parameters) if parameters else template.render()
        return query

    @classmethod
    def select(cls, conn, _query_name, sql, parameters: dict, record_class=None):
        sql = cls.render_template(sql, parameters)
        return super().select(
            conn, _query_name, sql, parameters, record_class=record_class
        )

    @classmethod
    def select_one(cls, conn, _query_name, sql, parameters: dict, record_class=None):
        sql = cls.render_template(sql, parameters)
        return super().select_one(
            conn, _query_name, sql, parameters, record_class=record_class
        )

    @classmethod
    @contextmanager
    def select_cursor(cls, conn, _query_name, sql, parameters: dict):
        sql = cls.render_template(sql, parameters)
        return super().select_cursor(conn, _query_name, sql, parameters)

    @classmethod
    def insert_update_delete(cls, conn, _query_name, sql, parameters: dict):
        sql = cls.render_template(sql, parameters)
        return super().insert_update_delete(conn, _query_name, sql, parameters)

    @classmethod
    def insert_update_delete_many(cls, conn, _query_name, sql, parmeters: t.List[dict]):
        sql = cls.render_template(sql, parmeters[0] if parmeters else {})
        return super().insert_update_delete_many(conn, _query_name, sql, parmeters)

    @classmethod
    def insert_returning(cls, conn, _query_name, sql, parameters: dict):
        sql = cls.render_template(sql, parameters)
        return super().insert_returning(conn, _query_name, sql, parameters)

    @classmethod
    def execute_script(cls, conn, sql):
        sql = cls.render_template(sql, parameters={})
        return super().execute_script(conn, sql)


def connect_test() -> connection:
    conn = psycopg2.connect(database="target_db", **credentials)
    return conn


def setup_test() -> None:
    conn = psycopg2.connect(database="postgres", **credentials)
    conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
    with conn.cursor() as cursor:
        cursor.execute("drop database if exists target_db")
        cursor.execute("create database target_db")
    conn.commit()
    conn.close()

    conn = psycopg2.connect(database="target_db", **credentials)
    queries = aiosql.from_path("sql/gargling.sql", "psycopg2")
    queries.create_schema(conn)
    for path in Path("sql/").iterdir():
        if path.stem == "gargling":
            continue
        queries = aiosql.from_path(path, "psycopg2")
        try:
            queries.create_schema(conn)
            queries.define_args(conn)
        except AttributeError:
            pass
    conn.commit()
    conn.close()


def get_migrations():
    setup_test()
    base = "postgresql+psycopg2://"
    with S(base, creator=connect) as current, S(base, creator=connect_test) as target:
        m = migra.Migration(current, target)
    return m


def migrate() -> None:
    conn = connect()
    queries = aiosql.from_path("sql/migrations.sql", "psycopg2")
    queries.migrations(conn)
    conn.commit()
    remaining_diffs = get_migrations()
    remaining_diffs.set_safety(False)
    remaining_diffs.add_all_changes()
    if remaining_diffs.statements:
        log.info(remaining_diffs.sql)


class MSN:
    def __init__(self):
        self.conn = connect()

    def main(self, cursor):
        for fname in os.listdir(os.path.join(config.home, "data", "logs")):
            if not fname.lower().endswith(".xml"):
                continue

            log.info(fname)
            for message_data in MSN.parse_log(fname):
                MSN.add_entry(cursor, *message_data)

        self.conn.commit()

    @staticmethod
    def parse_log(fname):
        with open(
            os.path.join(config.home, "data", "logs", fname), encoding="utf8"
        ) as infile:
            txt = infile.read()
        obj = parseString(
            txt.replace(b"\x1f".decode(), " ")
            .replace(b"\x02".decode(), " ")
            .replace(b"\x03".decode(), " ")
            .replace(b"\x04".decode(), " ")
            .replace(b"\x05".decode(), "|")
        )
        for message in obj.getElementsByTagName("Message") + obj.getElementsByTagName(
            "Invitation"
        ):
            msg_type = message.tagName.lower()
            msg_time = dt.datetime.strptime(
                message.getAttribute("DateTime"), "%Y-%m-%dT%H:%M:%S.%fZ"
            )
            msg_source = fname
            session_ID = msg_source + message.getAttribute("SessionID")

            from_node = message.getElementsByTagName("From")[0]
            user_from_node = from_node.getElementsByTagName("User")[0]
            from_user = user_from_node.getAttribute("FriendlyName")
            participants = set([user_from_node.getAttribute("LogonName")])

            text_node = message.getElementsByTagName("Text")[0]
            msg_text = text_node.firstChild.nodeValue
            match = re.search(r"color:(#\w{6})", text_node.getAttribute("Style"))
            msg_color = match.group(1) if match else None

            if msg_type == "message":
                to_node = message.getElementsByTagName("To")[0]
                user_to_nodes = to_node.getElementsByTagName("User")
                to_users = [node.getAttribute("FriendlyName") for node in user_to_nodes]
                participants.update(
                    node.getAttribute("LogonName") for node in user_to_nodes
                )
            elif msg_type == "invitation":
                to_users = None

            if not all(
                participant in config.gargling_msn_emails
                for participant in participants
            ):
                continue

            yield (
                session_ID,
                msg_type,
                msg_time,
                msg_source,
                msg_color,
                from_user,
                to_users,
                msg_text,
            )

    @staticmethod
    def add_entry(
        cursor,
        session_ID,
        msg_type,
        msg_time,
        msg_source,
        msg_color,
        from_user,
        to_users,
        msg_text,
    ):
        sql_command = (
            "INSERT INTO msn_messages (session_ID, msg_type, msg_source, "
            "msg_time, from_user, to_users, msg_text, msg_color) "
            "VALUES (%(session_ID)s, %(msg_type)s, %(msg_source)s, %(msg_time)s,"
            "%(from_user)s, %(to_users)s, %(msg_text)s, %(msg_color)s);"
        )
        data = {
            "session_ID": session_ID,
            "msg_type": msg_type,
            "msg_time": msg_time,
            "msg_source": msg_source,
            "msg_color": msg_color,
            "from_user": from_user,
            "to_users": str(to_users),
            "msg_text": msg_text,
        }
        cursor.execute(sql_command, data)

    @staticmethod
    def add_user_ids_to_msn():
        conn = connect()

        cursor = conn.cursor()
        sql_command = "SELECT slack_nick, db_id FROM user_ids"
        cursor.execute(sql_command)
        users = cursor.fetchall()
        for slack_nick, db_id in users:
            msn_nicks = config.slack_to_msn_nicks[slack_nick]
            for msn_nick in msn_nicks:
                sql_command = (
                    f"UPDATE msn_messages SET db_id = {db_id} "
                    f'WHERE from_user LIKE "%{msn_nick}%"'
                )
                cursor.execute(sql_command)
        conn.commit()
        conn.close()


def add_user_ids_table():
    conn = connect()
    users = []
    cursor = conn.cursor()
    for slack_id, db_id, slack_nick, first_name in users:
        sql_command = (
            "INSERT INTO user_ids (db_id, slack_id, slack_nick, first_name) "
            "VALUES (%(db_id)s, %(slack_id)s, %(slack_nick)s, %(first_name)s)"
        )
        data = {
            "slack_nick": slack_nick,
            "slack_id": slack_id,
            "db_id": db_id,
            "first_name": first_name,
        }
        cursor.execute(sql_command, data)
    conn.commit()
    conn.close()


class DropPics:
    def __init__(self):
        self.conn = None
        self.dbx = None
        self._firstname_to_db_id = None

    @property
    def firstname_to_db_id(self):
        if self._firstname_to_db_id is None:
            cursor = self.conn.cursor()
            sql_command = "SELECT first_name, db_id FROM user_ids"
            cursor.execute(sql_command)
            self._firstname_to_db_id = {
                row["first_name"]: row["db_id"] for row in cursor.fetchall()
            }
        return self._firstname_to_db_id

    def connect(self):
        self.conn = connect()

    def connect_dbx(self):
        self.dbx = dropbox.Dropbox(config.dropbox_token)
        self.dbx.users_get_current_account()
        log.info("Connected to dbx")

    @staticmethod
    def get_tags(image: t.Union[Path, str]) -> t.Optional[t.List[str]]:
        im = Image.open(image)
        exif = im._getexif()
        try:
            return exif[40094].decode("utf-16").rstrip("\x00").split(";")
        except KeyError:
            return None

    @staticmethod
    def get_date_taken(image: t.Union[Path, str]) -> dt.datetime:
        im = Image.open(image)
        exif = im._getexif()
        date_str = exif[36867]
        date_obj = dt.datetime.strptime(date_str, "%Y:%m:%d %H:%M:%S")
        return date_obj

    def add_faces_in_pic(self, cursor: LoggingCursor, pic: Path, dbx_path: str):
        sql_command = "SELECT pic_id FROM dbx_pictures WHERE path = %(path)s"
        data = {"path": dbx_path}
        cursor.execute(sql_command, data)
        try:
            pic_id = cursor.fetchone()["pic_id"]
        except KeyError:
            log.info(f"pic not in db: {dbx_path}")
            return

        sql_command = "SELECT * FROM dbx_pictures_faces WHERE pic_id = %(pic_id)s"
        data = {"pic_id": pic_id}
        cursor.execute(sql_command, data)
        result = cursor.fetchone()
        if result is not None:
            log.info(f"{dbx_path} pic faces already in db with id {pic_id}")
            return

        tags = DropPics.get_tags(pic)
        if tags is None:
            return
        faces = set(tags).intersection(self.firstname_to_db_id)
        for face in faces:
            db_id = self.firstname_to_db_id[face]
            sql_command = (
                "INSERT INTO dbx_pictures_faces (db_id, pic_id) "
                "VALUES (%(db_id)s, %(pic_id)s);"
            )
            data = {"db_id": db_id, "pic_id": pic_id}
            cursor.execute(sql_command, data)

    def add_pics_in_folder(self, folder: Path, topic: str, dbx_folder: str) -> None:
        cursor = self.conn.cursor()
        for pic in folder.iterdir():
            if not pic.suffix.lower() in {".jpg", ".jpeg"}:
                continue
            dbx_path = dbx_folder + "/" + pic.name.lower()

            sql_command = "SELECT pic_id FROM dbx_pictures WHERE path = %(path)s"
            data = {"path": dbx_path}
            cursor.execute(sql_command, data)
            if cursor.fetchone() is not None:
                log.info(f"{dbx_path} pic already in db")
                continue

            date_obj = DropPics.get_date_taken(pic)
            timestr = date_obj.strftime("%Y-%m-%d %H:%M:%S")

            sql_command = """INSERT INTO dbx_pictures (path, topic, taken)
            VALUES (%(path)s,
                   %(topic)s,
                   %(taken)s);"""
            data = {"path": dbx_path, "topic": topic, "taken": timestr}
            cursor.execute(sql_command, data)

            self.add_faces_in_pic(cursor, pic, dbx_path)
        self.conn.commit()

    def add_faces_to_existing_pics(self, folder: Path, dbx_folder: str):
        self.connect()
        try:
            for pic in list(folder.iterdir()):
                dbx_path = dbx_folder + "/" + pic.name.lower()
                with self.conn.cursor() as cursor:
                    self.add_faces_in_pic(cursor, pic, dbx_path)
        finally:
            self.conn.commit()
            self.conn.close()
