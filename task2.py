import os
import json
import threading
import time
import socket
import sys

from utils import cli, setup_socket

PACKET_SIZE_LIMIT = 576


class PersistentFrontierChat:
    def __init__(self, username, port, host, interval):
        self.username = username
        self.port = port
        self.host = host
        self.interval = interval
        self.state = self.load_frontier()
        self.lock = threading.Lock()
        self.running = True
        self.sock = setup_socket('', self.port)

        threading.Thread(target=self.listen, daemon=True).start()
        threading.Thread(target=self.broadcast_loop, daemon=True).start()

    def frontier_path(self, user, peer):
        return os.path.join("frontiers", user, f"{peer}.txt")

    def load_frontier(self):
        base_path = os.path.join("frontiers", self.username)
        state = {}
        if os.path.exists(base_path):
            for file in os.listdir(base_path):
                try:
                    with open(os.path.join(base_path, file), "r") as f:
                        count = int(f.read())
                        state[file.replace(".txt", "")] = count
                except Exception:
                    continue
        # Ensure own entry exists
        state[self.username] = state.get(self.username, 0)
        return state

    def save_frontier(self):
        base_path = os.path.join("frontiers", self.username)
        os.makedirs(base_path, exist_ok=True)
        for user, count in self.state.items():
            path = self.frontier_path(self.username, user)
            with open(path, "w") as f:
                f.write(str(count))

    def listen(self):
        while self.running:
            try:
                data, _ = self.sock.recvfrom(PACKET_SIZE_LIMIT)
                message = json.loads(data.decode("utf-8"))
                self.merge(message)
            except Exception as e:
                print("Error receiving packet:", e)

    def merge(self, incoming):
        with self.lock:
            changed = False
            for user, count in incoming.items():
                if user not in self.state or self.state[user] < count:
                    self.state[user] = count
                    changed = True
            if changed:
                self.save_frontier()
                self.print_state()

    def broadcast_loop(self):
        while self.running:
            time.sleep(self.interval)
            self.broadcast()

    def broadcast(self):
        with self.lock:
            message = json.dumps(self.state)
        self.sock.sendto(message.encode("utf-8"), (self.host, self.port))

    def increment_own_count(self):
        with self.lock:
            self.state[self.username] += 1
            self.save_frontier()
            self.print_state()

    def print_state(self):
        print("\nMessages sent:")
        for user, count in sorted(self.state.items()):
            print(f"  {user}: {count}")
        print("Press 'ENTER' to send message...")

    def run(self):
        print(f"Started chat as '{self.username}' with persistence.")
        try:
            while self.running:
                input()
                self.increment_own_count()
        except KeyboardInterrupt:
            self.running = False
            print("\nExiting...")


if __name__ == "__main__":
    username, port, host, interval, _ = cli()

    if len(username) > 16:
        print("Username too long (max 16 characters)")
        sys.exit(1)

    app = PersistentFrontierChat(username, port, host, interval)
    app.run()
