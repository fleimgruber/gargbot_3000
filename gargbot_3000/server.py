#! /usr/bin/env python3.6
# coding: utf-8
import contextlib
import json
import os
import typing as t

import requests
from dropbox import Dropbox
from flask import Flask, Response, jsonify, request
from flask_cors import CORS
from flask_jwt_extended import (
    JWTManager,
    create_access_token,
    get_jwt_identity,
    jwt_required,
)
from gunicorn.app.base import BaseApplication
from slackclient import SlackClient
from werkzeug.middleware.proxy_fix import ProxyFix

from gargbot_3000 import commands, config, database, health, pictures
from gargbot_3000.logger import log

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app)  # type: ignore
app.register_blueprint(health.blueprint)
app.pool = database.ConnectionPool()
app.dbx = Dropbox
app.config["JWT_SECRET_KEY"] = config.app_secret
jwt = JWTManager(app)
CORS(app)


@app.route("/")
def home_page() -> str:
    return "home"


@app.route("/version")
def version_page() -> str:
    return config.app_version


@app.route("/auth", methods=["GET"])
def auth():
    log.info(request)
    code = request.args["code"]
    log.info(request.args)
    log.info(code)
    client = SlackClient("")
    response = client.api_call(
        "oauth.access",
        redirect_uri=config.slack_redirect_url,
        client_id=config.slack_client_id,
        client_secret=config.slack_client_secret,
        code=code,
    )
    log.info(response)
    if not response["ok"]:
        log.info(f"Slack auth error: {response['error']}")
        return Response(status=403)
    if response["team_id"] != config.slack_team_id:
        return Response(status=403)
    slack_id = response["user_id"]
    with app.pool.get_connection() as conn:
        data = commands.queries.gargling_id_for_slack_id(conn, slack_id=slack_id)
        gargling_id = data["id"]
    access_token = create_access_token(identity=gargling_id, expires_delta=False)
    log.info(f"New token minted, for gargling {gargling_id}")
    return jsonify(access_token=access_token), 200


@app.route("/is_authed", methods=["GET"])
@jwt_required
def is_authed():
    gargling_id = get_jwt_identity()
    log.debug(gargling_id)
    return f"You are authenticated, {gargling_id}"


@app.route("/pic", methods=["GET"])
@app.route("/pic/<args>", methods=["GET"])
@jwt_required
def pic(args: t.Optional[str] = None):
    gargling_id = get_jwt_identity()
    log.info(gargling_id)
    arg_list = args.split(",") if args is not None else []
    with app.pool.get_connection() as conn:
        pic_url, *_ = pictures.get_pic(conn, app.dbx, arg_list=arg_list)
    return jsonify({"url": pic_url})


@app.route("/interactive", methods=["POST"])
def interactive() -> Response:
    log.info("incoming interactive request:")
    data = json.loads(request.form["payload"])
    log.info(data)
    if not data.get("token") == config.slack_verification_token:
        return Response(status=403)
    action_id = data["actions"][0]["action_id"]
    block_id = data["actions"][0]["block_id"]
    log.info(f"Interactive: {block_id}, {action_id}")
    if block_id == "share_buttons":
        result = handle_share_interaction(action_id, data)
    elif block_id == "commands_buttons":
        result = handle_command(command_str=action_id, args=[])
    response_url = data["response_url"]
    r = requests.post(response_url, json=result)
    r.raise_for_status()
    return Response(status=200)


@app.route("/slash", methods=["POST"])
def slash_cmds() -> Response:
    log.info("incoming slash request:")
    data = request.form
    log.info(data)

    if not data.get("token") == config.slack_verification_token:
        return Response(status=403)

    command_str = data["command"].replace("/", "")
    args = data["text"].replace("@", "").split()

    result = handle_command(command_str, args)
    log.info(f"result: {result}")
    response_url = data["response_url"]
    r = requests.post(response_url, json=result)
    r.raise_for_status()
    return Response(status=200)


def attach_share_buttons(result: dict, func: str, args: list) -> dict:
    buttons_block = {
        "type": "actions",
        "block_id": "share_buttons",
        "elements": [
            {
                "text": {"type": "plain_text", "text": "Del i kanal"},
                "type": "button",
                "action_id": "share",
                "style": "primary",
                "value": json.dumps(
                    {
                        "original_func": func,
                        "original_args": args,
                        "original_response": result,
                    }
                ),
            },
            {
                "text": {"type": "plain_text", "text": "Shuffle"},
                "type": "button",
                "action_id": "shuffle",
                "value": json.dumps({"original_func": func, "original_args": args}),
            },
            {
                "text": {"type": "plain_text", "text": "Avbryt"},
                "type": "button",
                "action_id": "cancel",
                "style": "danger",
            },
        ],
    }
    result["response_type"] = "ephemeral"
    try:
        result["blocks"].append(buttons_block)
    except KeyError:
        result["blocks"] = [buttons_block]
    return result


def attach_original_request(
    result: dict, slack_id: str, user_name: str, func: str, args: t.List[str]
) -> dict:
    with app.pool.get_connection() as conn:
        data = commands.queries.avatar_for_slack_id(conn, slack_id=slack_id)
        avatar_url = data["slack_avatar"]
    context_blocks = [
        {
            "type": "context",
            "elements": [
                {"type": "image", "image_url": avatar_url, "alt_text": user_name},
                {"type": "plain_text", "text": user_name},
            ],
        },
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"/{func} {' '.join(args)}"}],
        },
    ]
    try:
        result["blocks"][0:0] = context_blocks
    except KeyError:
        result["blocks"] = context_blocks

    return result


def attach_commands_buttons(result: dict) -> dict:
    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": result["text"]}},
        {"type": "section", "text": {"type": "plain_text", "text": "Try me:"}},
        {
            "type": "actions",
            "block_id": "commands_buttons",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": f"/{command}"},
                    "action_id": command,
                }
                for command in ["pic", "forum", "msn"]
            ],
        },
    ]
    result["blocks"] = blocks
    result["replace_original"] = True
    return result


def delete_ephemeral(response_url: str) -> None:
    delete_original = {
        "response_type": "ephemeral",
        "replace_original": True,
        "text": "Sharing is caring!",
    }
    r = requests.post(response_url, json=delete_original)
    r.raise_for_status()


def handle_share_interaction(action: str, data: dict) -> dict:
    if action == "share":
        response_url = data["response_url"]
        delete_ephemeral(response_url)

        action_data = json.loads(data["actions"][0]["value"])
        original_func = action_data["original_func"]
        original_args = action_data["original_args"]
        result = action_data["original_response"]
        result["replace_original"] = False
        result["response_type"] = "in_channel"
        result = attach_original_request(
            result=result,
            slack_id=data["user"]["id"],
            user_name=data["user"]["name"],
            func=original_func,
            args=original_args,
        )

    elif action == "cancel":
        result = {
            "response_type": "ephemeral",
            "replace_original": True,
            "text": (
                "Canceled! Går fint det. Ikke noe problem for meg. "
                "Hadde ikke lyst uansett."
            ),
        }
    elif action == "shuffle":
        action_data = json.loads(data["actions"][0]["value"])
        original_func = action_data["original_func"]
        original_args = action_data["original_args"]
        result = handle_command(original_func, original_args)
        result["replace_original"] = True
    return result


def handle_command(command_str: str, args: list) -> dict:
    db_func = (
        app.pool.get_connection
        if command_str in {"hvem", "pic", "forum", "msn"}
        else contextlib.nullcontext
    )
    with db_func() as conn:
        result = commands.execute(
            command_str=command_str, args=args, conn=conn, dbx=app.dbx
        )

    error = result.get("text", "").startswith("Error")
    if error:
        return result
    if command_str in {"ping", "hvem"}:
        result["response_type"] = "in_channel"
    elif command_str in {"pic", "forum", "msn"}:
        result = attach_share_buttons(result=result, func=command_str, args=args)
    elif command_str == "gargbot":
        result = attach_commands_buttons(result=result)
    return result


class StandaloneApplication(BaseApplication):
    def __init__(self, app, options: t.Dict[str, t.Any] = None) -> None:
        self.options = options if options is not None else {}
        self.application = app
        super().__init__()

    def load_config(self):
        for key, value in self.options.items():
            if key in self.cfg.settings and value is not None:
                self.cfg.set(key.lower(), value)

    def load(self):
        return self.application


def main(options: t.Optional[dict], debug: bool = False):
    try:
        app.pool.setup()
        with app.pool.get_connection() as conn:
            pictures.queries.define_args(conn)
            conn.commit()
        app.dbx = pictures.connect_dbx()
        if debug is False:
            gunicorn_app = StandaloneApplication(app, options)
            gunicorn_app.run()
        else:
            # Workaround for a werzeug reloader bug
            # (https://github.com/pallets/flask/issues/1246)
            os.environ["PYTHONPATH"] = os.getcwd()
            app.run(debug=True)
    except Exception:
        log.error("Error in server setup", exc_info=True)
    finally:
        if app.pool.is_setup:
            app.pool.closeall()
