"""Flask management interface."""

from __future__ import annotations

import os
import re
import json
import difflib
import shutil
import socket
import tempfile
from functools import wraps
from pathlib import Path

from flask import Flask, abort, redirect, render_template, request, send_file, session, url_for
from sqlalchemy import func, select
from waitress import serve

from .config import Settings, load_settings
from .database import session_factory
from .asterisk_config import SECRET_VALUE, is_secret_key, parse_config
from .generate import GENERATED_FILES, render_database
from .models import Change, ConfigValue, CustomLine, Network, Node, Setting
from .migrate import upgrade_database
from . import __version__


def create_app(settings: Settings | None = None) -> Flask:
    settings = settings or load_settings()
    app = Flask(__name__, template_folder="web/templates", static_folder="web/static")
    app.secret_key = _read_secret(settings.secret_key_file)
    app.config["MAX_CONTENT_LENGTH"] = 104_857_600
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")
    sessions = session_factory(settings.database)
    engine = sessions.kw["bind"]

    def current_user() -> str | None:
        return session.get("username")

    def writers() -> set[str]:
        try:
            return {line.strip() for line in settings.writer_allowlist.read_text().splitlines()
                    if line.strip() and not line.lstrip().startswith("#")}
        except OSError:
            return set()

    def login_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not current_user():
                return redirect(url_for("login", next=request.path))
            return view(*args, **kwargs)
        return wrapped

    def write_required(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if current_user() not in writers():
                abort(403)
            return view(*args, **kwargs)
        return wrapped

    app.jinja_env.globals["is_writer"] = lambda: current_user() in writers()

    @app.get("/login")
    def login():
        return render_template("login.html", error=None)

    @app.post("/login")
    def login_post():
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if not username or not password or not _request_authentication(settings, username, password):
            return render_template("login.html", error="Login failed"), 401
        session.clear()
        session["username"] = username
        return redirect(request.args.get("next") or url_for("index"))

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.get("/")
    @login_required
    def index():
        with sessions() as db:
            node_count = db.query(func.count(Node.id)).scalar()
            networks = db.query(Network).order_by(Network.name).all()
            nodes = db.query(Node).order_by(Node.node_number).all()
            values = {row.key: row.value for row in db.scalars(select(Setting))}
            changes = db.scalars(select(Change).order_by(Change.revision.desc()).limit(20)).all()
        return render_template("index.html", node_count=node_count, networks=networks,
                               nodes=nodes, username=current_user(),
                               default_network=values.get("default_network_key", ""),
                               advanced_networks=values.get("advanced_node_networks") == "true",
                               changes=changes)

    @app.post("/nodes")
    @write_required
    def create_node():
        try:
            node_number = int(request.form.get("node_number", ""))
        except ValueError:
            abort(400, "Node Number must be an integer")
        name = request.form.get("name", "").strip()
        if node_number < 1 or not name or len(name) > 200:
            abort(400, "Provide a positive Node Number and a name")
        with sessions() as db:
            if db.scalar(select(Node.id).where(Node.node_number == node_number)) is not None:
                abort(409, "That Node Number is already configured")
        with sessions.begin() as db:
            db.add(Node(node_number=node_number, name=name, settings={}))
            _record_change(db, current_user() or "", f"Added node {node_number}",
                           {"record": "node", "node_number": node_number, "operation": "create"})
        engine.dispose()
        _regenerate_or_503(settings)
        return redirect(url_for("index"))

    @app.post("/nodes/<int:node_id>/delete")
    @write_required
    def delete_node(node_id: int):
        with sessions.begin() as db:
            node = db.get(Node, node_id)
            if node is None:
                abort(404)
            db.delete(node)
            node_number = node.node_number
            _record_change(db, current_user() or "", f"Removed node {node_number}",
                           {"record": "node", "node_number": node_number, "operation": "delete"})
        engine.dispose()
        _regenerate_or_503(settings)
        return redirect(url_for("index"))

    @app.post("/nodes/<int:node_id>/network")
    @write_required
    def assign_network(node_id: int):
        with sessions.begin() as db:
            node = db.get(Node, node_id)
            if node is None:
                abort(404)
            raw_id = request.form.get("network_id", "")
            if raw_id:
                try:
                    network_id = int(raw_id)
                except ValueError:
                    abort(400, "Choose a valid network profile")
                network = db.get(Network, network_id)
                if network is None:
                    abort(400, "Unknown network profile")
                node.network = network
            else:
                node.network = None
            _record_change(db, current_user() or "", f"Changed network for node {node.node_number}",
                           {"record": "node", "node_number": node.node_number,
        -üç‹h‘éì¶»§q«^uHŸJK™[˜ÛÙJ]‹NŠBˆÚ]ÛØÚÙ]œÛØÚÙ]
ÛØÚÙ]Q—ÕS’VÛØÚÙ]”ÓĞÒ×ÔÕ‘PSJH\ÈÛY[‚ˆÛY[œÙ][Y[İ]
Ì
BˆÛY[˜ÛÛ›™Xİ
İŠÙ][™ÜËÜš]\—ÜÛØÚÙ]
JBˆÛY[œÙ[™[
™\]Y\İÙ]JBˆ™\ÜÛœÙHHœÛÛ‹›ØYÊÛY[œ™XİŠMLÍŠK™XÛÙJ]‹NŠJBˆYˆ›İ™\ÜÛœÙK™Ù]
›ÚÈŠN‚ˆ˜Z\ÙHÔÑ\œ›ÜŠ™\ÜÛœÙK™Ù]
™\œ›Üˆ‹˜ÛÛ™šYİ\˜][ÛˆÙ[™\˜][Ûˆ˜Z[YŠJB‚‚™YˆÜ™\]Y\İØ]][XØ][ÛŠÙ][™ÜÎˆÙ][™ÜË\Ù\›˜[YNˆİ‹\ÜİÛÜ™ˆİŠHOˆ›ÛÛ‚ˆ™\]Y\İÙ]HHœÛÛ‹™[\ÊÈ›Ü\˜][Ûˆˆ˜]][XØ]H‹\Ù\›˜[YHˆ\Ù\›˜[YKˆœ\ÜİÛÜ™ˆ\ÜİÛÜ™œÙ\šXÙHˆÙ][™ÜËœ[WÜÙ\šXÙ_JK™[˜ÛÙJ]‹NŠBˆÚ]ÛØÚÙ]œÛØÚÙ]
ÛØÚÙ]Q—ÕS’VÛØÚÙ]”ÓĞÒ×ÔÕ‘PSJH\ÈÛY[‚ˆÛY[œÙ][Y[İ]
MJBˆÛY[˜ÛÛ›™Xİ
İŠÙ][™ÜËÜš]\—ÜÛØÚÙ]
JBˆÛY[œÙ[™[
™\]Y\İÙ]JBˆ™\ÜÛœÙHHœÛÛ‹›ØYÊÛY[œ™XİŠMLÍŠK™XÛÙJ]‹NŠJBˆ™]\›ˆ›ÛÛ
™\ÜÛœÙK™Ù]
˜]][XØ]YŠJB‚‚™YˆÜ™\]Y\İÙXYÛ›ÜİXÊÙ][™ÜÎˆÙ][™ÜËÛÛ[X[™ˆİŠHOˆİ‚ˆ™\]Y\İÙ]HHœÛÛ‹™[\ÊÈ›Ü\˜][Ûˆˆ™XYÛ›ÜİXÈ‹˜ÛÛ[X[™ˆÛÛ[X[™JK™[˜ÛÙJ]‹NŠBˆÚ]ÛØÚÙ]œÛØÚÙ]
ÛØÚÙ]Q—ÕS’VÛØÚÙ]”ÓĞÒ×ÔÕ‘PSJH\ÈÛY[‚ˆÛY[œÙ][Y[İ]
MJBˆÛY[˜ÛÛ›™Xİ
İŠÙ][™ÜËÜš]\—ÜÛØÚÙ]
JBˆÛY[œÙ[™[
™\]Y\İÙ]JBˆ™\ÜÛœÙHHœÛÛ‹›ØYÊÛY[œ™XİŠMLÍŠK™XÛÙJ]‹NŠJBˆYˆ›İ™\ÜÛœÙK™Ù]
›ÚÈŠN‚ˆ˜Z\ÙHÔÑ\œ›ÜŠ™\ÜÛœÙK™Ù]
™\œ›Üˆ‹\İ\š\ÚÈXYÛ›ÜİXÈ˜Z[YŠJBˆ™]\›ˆİŠ™\ÜÛœÙK™Ù]
›İ]]‹ˆŠJB‚‚™YˆÜ™XÛÜ™ØÚ[™ÙJ‹XİÜˆİ‹İ[[X\Nˆİ‹]Z[ÎˆXİ›Û™HH›Û™JHOˆ›Û™N‚ˆ]\İH‹œØØ[\ŠÙ[Xİ
[˜Ë›X^
Ú[™ÙKœ™]š\Ú[ÛŠJJHÜˆˆ‹˜Y
Ú[™ÙJXİÜXXİÜ‹İ[[X\O\İ[[X\K™]š\Ú[Û[]\İ
ÈK]Z[ÏY]Z[ÈÜˆßJJB‚‚™YˆÜØ]™WØÛÛ™šY×Ùš[J‹š[[˜[YNˆİ‹˜[Y\ÎˆXİ™\Ù\™YˆXİ
HOˆ›Û™N‚ˆš[Ü—İ˜[Y\ÈHÊ›İËœÙXİ[Û‹›İËšÙ^JNˆ›İÈ›Üˆ›İÈ[‚ˆ‹œØØ[\œÊÙ[Xİ
ÛÛ™šYÕ˜[YJKÚ\™JÛÛ™šYÕ˜[YK™š[WÛ˜[YHOHš[[˜[YJJ_Bˆ‹œ]Y\JÛÛ™šYÕ˜[YJK™š[\—ØJš[WÛ˜[YOYš[[˜[YJK™[]J
Bˆ‹œ]Y\Jİ\İÛS[™JK™š[\—ØJš[WÛ˜[YOYš[[˜[YJK™[]J
BˆYˆš[[˜[YHOHœœ˜ÛÛ™ˆ‚ˆ^\İ[™×Û›Ù\ÈHÜİŠ›ÙK››ÙWÛ[X™\ŠNˆ›ÙH›Üˆ›ÙH[ˆ‹œØØ[\œÊÙ[Xİ
›ÙJJ_Bˆ™]Z[™YˆÙ]Üİ—HHÙ]

Bˆ›ÜˆÙXİ[Û‹[šY\È[ˆ˜[Y\Ëš][\Ê
N‚ˆYˆÙXİ[Û‹š\ÙYÚ]

N‚ˆ™]Z[™Y˜Y
ÙXİ[ÛŠBˆ›ÙHH^\İ[™×Û›Ù\Ë™Ù]
ÙXİ[ÛŠBˆYˆ›ÙH\È›Û™N‚ˆ‹˜Y
›ÙJ›ÙWÛ[X™\Z[
ÙXİ[ÛŠK˜[YOYˆ“›ÙHÜÙXİ[ÛŸH‹Ù][™ÜÏY[šY\ÊJBˆ[ÙN‚ˆ›ÙKœÙ][™ÜÈHÜ™\İÜ™WÚY[—ÜÙ][™ÜÊ[šY\Ë›ÙKœÙ][™ÜÊBˆÛÛ[YBˆ›ÜˆÙ^K˜[YH[ˆ[šY\Ëš][\Ê
N‚ˆ™]š[İ\ÈHš[Ü—İ˜[Y\Ë™Ù]

ÙXİ[Û‹Ù^JJBˆYˆ˜[YHOHÑPÔ‘UÕSQH[™™]š[İ\È\È›İ›Û™H[™™]š[İ\ËœÙXÜ™]‚ˆ˜[YHH™]š[İ\Ë˜[YBˆ‹˜Y
ÛÛ™šYÕ˜[YJš[WÛ˜[YOYš[[˜[YKÙXİ[Û\ÙXİ[Û‹Ù^OZÙ^K˜[YO]˜[YKˆÙXÜ™]Z\×ÜÙXÜ™]ÚÙ^JÙ^JJJBˆ›ÜˆÙXİ[Û‹›ÙH[ˆ^\İ[™×Û›Ù\Ëš][\Ê
N‚ˆYˆÙXİ[Ûˆ›İ[ˆ™]Z[™Y‚ˆ‹™[]J›ÙJBˆ[ÙN‚ˆ›ÜˆÙXİ[Û‹[šY\È[ˆ˜[Y\Ëš][\Ê
N‚ˆ›ÜˆÙ^K˜[YH[ˆ[šY\Ëš][\Ê
N‚ˆ™]š[İ\ÈHš[Ü—İ˜[Y\Ë™Ù]

ÙXİ[Û‹Ù^JJBˆYˆ˜[YHOHÑPÔ‘UÕSQH[™™]š[İ\È\È›İ›Û™H[™™]š[İ\ËœÙXÜ™]‚ˆ˜[YHH™]š[İ\Ë˜[YBˆ‹˜Y
ÛÛ™šYÕ˜[YJš[WÛ˜[YOYš[[˜[YKÙXİ[Û\ÙXİ[Û‹Ù^OZÙ^K˜[YO]˜[YKˆÙXÜ™]Z\×ÜÙXÜ™]ÚÙ^JÙ^JJJBˆ›ÜˆÙXİ[Û‹[™\È[ˆ™\Ù\™Yš][\Ê
N‚ˆ›Üˆ[™^[™H[ˆ[[Y\˜]J[™\ÊN‚ˆ‹˜Y
İ\İÛS[™Jš[WÛ˜[YOYš[[˜[YKÙXİ[Û\ÙXİ[Û‹[™WÛ[X™\Z[™^ÛÛ[[[™JJB‚‚™YˆÜ™\İÜ™WÚY[—ÜÙ][™ÜÊ™]ÎˆXİÜİ‹İ—KÛˆXİÜİ‹İ—JHOˆXİÜİ‹İ—N‚ˆ™\İ[HXİ
™]ÊBˆ›ÜˆÙ^K˜[YH[ˆ™\İ[š][\Ê
N‚ˆYˆ˜[YHOHÑPÔ‘UÕSQH[™Ù^H[ˆÛ[™\×ÜÙXÜ™]ÚÙ^JÙ^JN‚ˆ™\İ[ÚÙ^WHHÛÚÙ^WBˆ™]\›ˆ™\İ[‚‚™YˆÛX\Ú×ÜÙXÜ™]Ê^ˆİŠHOˆİ‚ˆX\ÚÙYH×Bˆ›Üˆ[™H[ˆ^œÜ][™\Ê
N‚ˆYˆHˆ[ˆ[™H[™›İ[™K›İš\

Kœİ\İÚ]

È‹ˆÈŠJN‚ˆÙ^K˜[YHH[™KœÜ]
H‹JBˆYˆ\×ÜÙXÜ™]ÚÙ^JÙ^Kœİš\

JH[™˜[YKœİš\

N‚ˆ[™HHˆÚÙ^_HHÔÑPÔ‘UÕSQ_H‚ˆX\ÚÙY˜\[™
[™JBˆ™]\›ˆ—ˆ‹š›Ú[ŠX\ÚÙY
H
È
—ˆˆYˆ^™[™İÚ]
—ˆŠH[ÙHˆŠB‚‚™YˆÜ™YÙ[™\˜]WÛÜ—ÍLÊÙ][™ÜÎˆÙ][™ÜÊHOˆ›Û™N‚ˆN‚ˆÜ™\]Y\İÙÙ[™\˜][ÛŠÙ][™ÜÊBˆ^Ù\ÔÑ\œ›Üˆ\È^Î‚ˆX›Ü
LËˆ‘]X˜\ÙHÚ[™ÙHØ\ÈØ]™Y]š[HÙ[™\˜][Ûˆ˜Z[YˆÙ^ßHŠB‚‚™YˆÜ™XYÜÙXÜ™]
]ˆ]
HOˆİ‚ˆN‚ˆ˜[YHH]œ™XYİ^

Kœİš\

BˆYˆ˜[YN‚ˆ™]\›ˆ˜[YBˆ^Ù\ÔÑ\œ›Ü‚ˆ\ÜÂˆYˆÜË™[š\›Û‹™Ù]
TÕT’TÒ×Ó“ÑWÓPSQÑT—ÑUˆŠHOHŒH‚ˆ™]\›ˆ™]™[ÜY[[Û›KXÚ[™ÙK[YH‚ˆ˜Z\ÙH[[YQ\œ›ÜŠˆ“Z\ÜÚ[™È›\ÚÈÙXÜ™]Ù^NˆÜ]HŠB‚‚™YˆXZ[Š
HOˆ[‚ˆÙ][™ÜÈHØYÜÙ][™ÜÊ
BˆÙ\™JÜ™X]WØ\
Ù][™ÜÊKÜİ\Ù][™ÜË›\İ[—ØY™\ÜËÜ\Ù][™ÜËœÜ
Bˆ™]\›ˆ‚‚šYˆ×Û˜[YW×ÈOH—×ÛXZ[—×È‚ˆ˜Z\ÙHŞ\İ[Q^]
XZ[Š
JB