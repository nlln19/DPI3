import json
import threading
import time
import sys

from utils import cli, setup_socket

PACKET_SIZE_LIMIT = 576


class FrontierChat:
    def __init__(self, username, port, host, interval):
        self.username = username
        self.state = {username: 0}  # eigene Nachrichtenzahl
        self.lock = threading.Lock()
        self.running = True
        self.port = port
        self.host = host
        self.interval = interval

        # UDP Socket für Broadcast (aus utils.py)
        self.sock = setup_socket('', self.port)

        # Empfang starten
        threading.Thread(target=self.listen, daemon=True).start()

        # Broadcast starten (alle x Sekunden)
        threading.Thread(target=self.broadcast_loop, daemon=True).start()

    def listen(self):
        while self.running:
            try:
                data, _ = self.sock.recvfrom(PACKET_SIZE_LIMIT)
                message = json.loads(data.decode('utf-8'))
                self.merge(message)
            except Exception as e:
                print("Fehler beim Empfang:", e)

    def merge(self, incoming_state):
        with self.lock:
            changed = False
            for user, count in incoming_state.items():
                if user not in self.state or self.state[user] < count:
                    self.state[user] = count
                    changed = True
            if changed:
                self.print_state()

    def broadcast_loop(self):
        while self.running:
            time.sleep(self.interval)
            self.broadcast()

    def broadcast(self):
        with self.lock:
            message = json.dumps(self.state)
        self.sock.sendto(message.encode('utf-8'), (self.host, self.port))

    def increment_own_count(self):
        with self.lock:
            self.state[self.username] += 1
            self.print_state()

    def print_state(self):
        print("\nMessages sent:")
        for user, count in sorted(self.state.items()):
            print(f"  {user}: {count}")
        print("Press 'ENTER' to send message...")

    def run(self):
        print(f"Started chat as '{self.username}'. Press 'ENTER' to simulate sending a message.")
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

    app = FrontierChat(username, port, host, interval)
    app.run()
