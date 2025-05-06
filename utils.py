import argparse
import os
import socket
import subprocess


def cli():
    parser = argparse.ArgumentParser()
    parser.add_argument("username")
    parser.add_argument(
        "-i",
        "--interval",
        nargs="?",
        default=10,
        type=int,
        help="The broadcast interval in seconds",
    )
    parser.add_argument(
        "-p",
        "--port",
        nargs="?",
        default=9999,
        type=int,
        help="The port where the application is listening",
    )
    parser.add_argument(
        "-o",
        "--host",
        nargs="?",
        default="<broadcast>",
        help="IPv4 address or hostname of this client",
    )
    # Can be ignored in task01
    parser.add_argument(
        "-t",
        "--temp",
        action="store_true",
        help="If set, a temporary replica is created",
    )
    args = parser.parse_args()
    return args.username, args.port, args.host, args.interval, args.temp


def run(command: list[str], env=None, input=None):
    return subprocess.run(
        command,
        input=input,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        env=env if env else os.environ,
    ).stdout.strip()


def setup_socket(host: str, port: int):
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    client_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    client_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    client_socket.bind((host, port))
    return client_socket
