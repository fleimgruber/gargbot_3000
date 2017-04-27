#! /usr/bin/env python3.6
# coding: utf-8
from logger import log

import re
import html
import random
from operator import itemgetter
import os
from os import path
from xml.dom.minidom import parseString
import datetime as dt

import MySQLdb
import requests

import config


home = os.getcwd()


garg_ids_to_slack_nicks = {
    2: "asmundboe",
    3: "gromsten",
    5: "eirki",
    6: "nils",
    7: "lbs",
    9: "kenlee",
    10: "cmr",
    11: "smorten",
}

slack_nicks_to_garg_ids = {
    "asmundboe": 2,
    "gromsten": 3,
    "eirki": 5,
    "nils": 6,
    "lbs": 7,
    "kenlee": 9,
    "cmr": 10,
    "smorten": 11,
}

slack_to_msn_nicks = {
    "asmundboe": ["åsmund", "aab", "aasmund", "vismund cygnus"],
    "gromsten": ["pelle", "gromsten", "pell-e"],
    "eirki": ["eika", "eirik", "sem", "ulf fjorddrott", "alf", "dix", "eeiorik"],
    "nils": ["guleful", "nils", "nisl"],
    "lbs": ["cubikar", "lbs", "labben", "lars", "læbbes"],
    "kenlee": ["ero-ken", "kenneth"],
    "cmr":  ["carl martin"],
    "smorten":  [],
}


class Garg:
    @staticmethod
    def _sanitize(inp, bbcode_uid):
        smls = re.compile(r'<!-- s.*? --><img src=\\?"\{SMILIES_PATH\}/.*?\\?" alt=\\?"(.*?)\\?" title=\\?".*?" /><!-- s.*? -->')
        inp = re.sub(smls, r"\1", inp)
        inp = html.unescape(inp)

        inp = inp.replace(":" + bbcode_uid, "")

        img_tags = re.compile(r"\[/?img\]")
        inp = re.sub(img_tags, "", inp)

        youtube_embeds = re.compile(r'\[html\]<iframe width="\d+" height="\d+" src="//www.youtube.com/embed/([^"]+)" frameborder='
                                    r'0" allowfullscreen></iframe>\[/html\]')
        inp = re.sub(youtube_embeds, r"https://www.youtube.com/watch?v=\1", inp)

        return inp

    @staticmethod
    def _fetch_url(cursor, topic_id, extract_func):
        sql = f"SELECT post_text, bbcode_uid FROM phpbb_posts WHERE topic_id = {topic_id} ORDER BY RAND() LIMIT 1"
        for _ in range(20):
            cursor.execute(sql)
            post_text, bbcode_uid = cursor.fetchall()[0]
            sanitized = Garg._sanitize(post_text, bbcode_uid)
            try:
                url = extract_func(sanitized)
                if requests.get(url).status_code == 200:
                    return url
            except (AttributeError, requests.exceptions.RequestException):
                continue

    @staticmethod
    def quote(cursor, user=None):
        if user and user not in slack_nicks_to_garg_ids:
            return f"Gargling not found: {user}. Husk å bruke slack id"

        if user:
            user_filter = f"= {slack_nicks_to_garg_ids[user]}"
        else:
            user_filter = "IN (2, 3, 5, 6, 7, 9, 10, 11)"

        sql = ("SELECT poster_id, post_text, post_time, post_id, bbcode_uid "
               f"FROM phpbb_posts WHERE poster_id {user_filter} ORDER BY RAND() LIMIT 1")

        cursor.execute(sql)
        poster_id, post_text, post_time, post_id, bbcode_uid = cursor.fetchall()[0]
        user = user if user is not None else garg_ids_to_slack_nicks[poster_id]
        post = Garg._sanitize(post_text, bbcode_uid)
        quote = (
            f"{post}\n"
            "------\n"
            f"- {user}\n"
            f"http://eirik.stavestrand.no/gargen/viewtopic.php?p={post_id}#p{post_id}\n")
        return quote

    @staticmethod
    def random(cursor):
        def extract(text):
            match = re.search("(?P<url>https?://[^\s]+)", text)
            return match.group("url")
        url = Garg._fetch_url(cursor, topic_id=636, extract_func=extract)
        return url

    @staticmethod
    def vidoi(cursor):
        def extract(text):
            match = re.search(r"(https://www.youtube.com/watch\?v=.{11})", text)
            return match.group(1)
        url = Garg._fetch_url(cursor, topic_id=563, extract_func=extract)
        return url


class MSN:
    garglings = {
        "",
        "chegivarix@yahoo.no",
        "cubikar@hotmail.com",
        "gromsten@hotmail.com",
        "guleful@hotmail.com",
        "wootyboe@hotmail.com"
    }

    @staticmethod
    def db_setup(cursor, db):
        cursor.execute("DROP TABLE IF EXISTS msn_messages")
        sql_command = """
        CREATE TABLE msn_messages (
        session_ID CHAR(50),
        msg_type CHAR(10),
        msg_time DATETIME(3),
        msg_source CHAR(10),
        msg_color CHAR(10),
        from_user CHAR(200),
        to_users TEXT,
        msg_text TEXT);
        """
        cursor.execute(sql_command)
        for fname in os.listdir(path.join(home, "data", "logs")):
            if not fname.lower().endswith(".xml"):
                continue

            log.info(fname)
            for message_data in MSN.parse_log(fname):
                MSN.add_entry(cursor, *message_data)

        db.commit()

    @staticmethod
    def parse_log(fname):
        with open(path.join(home, "data", "logs", fname), encoding="utf8") as infile:
            txt = infile.read()
        obj = parseString(txt.replace(b"\x1f".decode(), " ").replace(b"\x02".decode(), " ").replace(b"\x03".decode(), " ").replace(b"\x04".decode(), " ").replace(b"\x05".decode(), "|"))
        for message in obj.getElementsByTagName("Message") + obj.getElementsByTagName("Invitation"):
            msg_type = message.tagName.lower()
            msg_time = dt.datetime.strptime(message.getAttribute("DateTime"), "%Y-%m-%dT%H:%M:%S.%fZ")
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
                participants.update(node.getAttribute("LogonName") for node in user_to_nodes)
            elif msg_type == "invitation":
                to_users = None

            if not all(participant in MSN.garglings for participant in participants):
                continue

            yield session_ID, msg_type, msg_time, msg_source, msg_color, from_user, to_users, msg_text

    @staticmethod
    def add_entry(cursor, session_ID, msg_type, msg_time, msg_source, msg_color, from_user, to_users, msg_text):
        sql_command = """INSERT INTO msn_messages (session_ID, msg_type, msg_source, msg_time, from_user, to_users, msg_text, msg_color)
        VALUES (%(session_ID)s,
               %(msg_type)s,
               %(msg_source)s,
               %(msg_time)s,
               %(from_user)s,
               %(to_users)s,
               %(msg_text)s,
               %(msg_color)s);"""

        data = {
            "session_ID": session_ID,
            "msg_type": msg_type,
            "msg_time": msg_time,
            "msg_source": msg_source,
            "msg_color": msg_color,
            "from_user": from_user,
            "to_users": str(to_users),
            "msg_text": msg_text
        }
        try:
            cursor.execute(sql_command, data)
        except:
            print(sql_command % data)
            raise

    @staticmethod
    def quote(cursor, user=None):
        if user is not None:
            user_nicks = slack_to_msn_nicks[user]
            filter = " WHERE " + " OR ".join([f'from_user LIKE "%{name}%"'
                                              for name in user_nicks])
        else:
            filter = ""
        sql = f"SELECT session_ID FROM msn_messages {filter} ORDER BY RAND() LIMIT 1"
        log.info(sql)
        cursor.execute(sql)
        session_ID = cursor.fetchone()[0]
        log.info(session_ID)
        sql = ("SELECT msg_time, from_user, to_users, msg_text, msg_color "
               f'FROM msn_messages WHERE session_ID = "{session_ID}"')
        log.info(sql)
        cursor.execute(sql)
        messages = list(cursor.fetchall())
        messages.sort(key=itemgetter(0))
        if user is not None:
            first = next(i for i, message in enumerate(messages) if any(nick in message[1].lower()
                                                                        for nick in user_nicks))
        elif len(messages) <= 10:
            first = 0
        else:
            first = random.randint(0, len(messages)-10)
        chosen = messages[first:first+10]

        date = chosen[0][0].strftime("%d.%m.%y %H:%M")

        convo = []
        for msg_time, from_user, to_users, msg_text, msg_color in chosen:
            if convo:
                prev_from_user, prev_msg_text, prev_msg_color = convo[-1]
                if from_user == prev_from_user:
                    convo[-1][1] = "\n".join([prev_msg_text, msg_text])
                    continue
            convo.append([from_user, msg_text, msg_color])

        return date, convo


class Quotes:
    def connect(self):
        self.db = MySQLdb.connect(host=config.db_host, user=config.db_user,
                                  passwd=config.db_passwd, db=config.db_name, charset="utf8")
        self.c = self.db.cursor()
        log.info("Connected to gargen database")

    def teardown(self):
        self.db.close()

    def garg(self, func, *args):
        switch = {
            "quote": Garg.quote,
            "random": Garg.random,
            "vidoi": Garg.vidoi,
        }
        selected = switch[func]
        result = selected(self.c, *args)
        return result

    def msn(self, user=None):
        result = MSN.quote(self.c, user)
        return result


if __name__ == "__main__":
    quotes_db = Quotes()
    quotes_db.connect()
    try:
        log.info(quotes_db.garg("quote"))
        log.info(quotes_db.garg("vidoi"))
        log.info(quotes_db.garg("random"))
        log.info(quotes_db.msn(user="cmr"))
    finally:
        quotes_db.teardown()