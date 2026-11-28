"""Named, read-only Asterisk CLI queries used by live-operation tooling."""

from __future__ import annotations

from pathlib import Path

from .base import AsteriskSocket, OperationError


QUERY_COMMANDS = {
    "version": "core show version",
    "uptime": "core show uptime",
    "channels": "core show channels",
    "iax_peers": "iax2 show peers",
    "rpt_nodes": "rpt localnodes",
    "modules": "module show",
}

DEMO_QUERY_OUTPUTS = {
    "version": "Asterisk 20.7.0-demo built for demonstration\n",
    "uptime": "System uptime: 2 hours, 14 minutes\nLast reload: 18 minutes ago\n",
    "channels": "Channel              Location             State   Application\n0 active channels\n",
    "iax_peers": "Name/Username    Host             State\nDemoPeer         192.0.2.25       OK\n",
    "rpt_nodes": "Node 1000: Demo Node North\nNode 1001: Demo Node South\n",
    "modules": "Module                         Description\napp_rpt.so                     Radio Repeater\n",
}


def query_asterisk(asterisk_socket: AsteriskSocket, query: str) -> str:
    """Execute one named read-only query; arbitrary CLI input is never accepted."""
    command = QUERY_COMMANDS.get(query)
    if command is None:
        raise OperationError("Choose a supported read-only Asterisk query.")
    return asterisk_socket.run(command)


def query_demo_asterisk(query: str) -> str:
    """Return representative command output for isolated demo mode."""
    try:
        return DEMO_QUERY_OUTPUTS[query]
    except KeyError as exc:
        raise OperationError("Choose a supported read-only Asterisk query.") from exc


def execute_query(asterisk_socket_path: Path, query: str) -> dict[str, str]:
    """Execute one registered status query through the shared operation transport."""
    return {"output": query_asterisk(AsteriskSocket(asterisk_socket_path), query)}
