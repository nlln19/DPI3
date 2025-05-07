import socket
import json
import threading
import time
import sys
import os
import tempfile
import shutil
from utils import run


BROADCAST_PORT = 6969
PACKET_LIMIT = 576
FRONTIER_DIR = "frontiers"

class GitbasedChat:
    def __init__(self, username, temp):
        self.username = username
        self.temp = temp
        self.running = True
        self.lock = threading.Lock()
        self.pending_commits = []  # Queue for out-of-order commits

        if self.temp:
            self.temp_dir = tempfile.TemporaryDirectory()
            os.chdir(self.temp_dir.name)
            run(["git", "init", "-b", self.username])
            run(["git", "config", "user.name", self.username])
            run(["git", "config", "user.email", f"{self.username}@example.com"])
            empty_tree = run(["git", "mktree"], input="")
            init_commit = run(["git", "commit-tree", empty_tree], input=f"{self.username} joined (temp mode)")
            run(["git", "update-ref", f"refs/heads/{self.username}", init_commit])
            run(["git", "symbolic-ref", "HEAD", f"refs/heads/{self.username}"])
        else:
            if not os.path.exists(".git"):
                print("Error: Not inside a Git repository.")
                sys.exit(1)

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.sock.sendto(b'test', (('255.255.255.255', 6969)))

        try:
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except Exception:
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        try:
            self.sock.bind(('', BROADCAST_PORT))
        except Exception as e:
            print(f"Could not bind to port {BROADCAST_PORT}: {e}")
            sys.exit(1)

        print(f"[{self.username}] Listening on UDP port {BROADCAST_PORT}")

        threading.Thread(target=self.listen, daemon=True).start()
        threading.Thread(target=self.broadcast_loop, daemon=True).start()
        threading.Thread(target=self.retry_pending_commits, daemon=True).start()

    def broadcast_loop(self):
        while self.running:
            time.sleep(10)
            self.send_frontier()
            self.print_frontier()

    def listen(self):
        while self.running:
            try:
                data, addr = self.sock.recvfrom(PACKET_LIMIT)
                msg = json.loads(data.decode('utf-8'))
                self.handle_message(msg, addr)
            except Exception as e:
                print("Error receiving or handeling message: ", e)

    def send_frontier(self):
        with self.lock:
            frontier = self.get_frontier_local()
            msg = {
                "type": "frontier",
                "from": self.username,
                "frontier": frontier
            }
        print(f"[{self.username}] Broadcasting frontier: {frontier}")
        try:
            self.sock.sendto(json.dumps(msg).encode('utf-8'), ('255.255.255.255', BROADCAST_PORT))
        except Exception as e:
            print(f"Error sending broadcast: {e}")

    def get_frontier_local(self):
        refs = run(["git", "for-each-ref", "--format=%(refname)"]).splitlines()
        frontier = {}
        for ref in refs:
            if ref.startswith("refs/heads/"):
                user = ref.split("/")[-1]
                count = run(["git", "rev-list", "--count", ref])
                frontier[user] = int(count)
        return frontier

    def handle_message(self, msg, addr):
        if msg["type"] == "frontier":
            print(f"[{self.username}] Received frontier from {msg['from']}: #{msg['frontier']}")
            missing = self.get_missing_commits(msg["frontier"])
            for commit_hash in missing:
                packet = self.create_commit_packet(commit_hash)
                try:
                    self.sock.sendto(json.dumps(packet).encode(), addr)
                except Exception as e:
                    print(f"[{self.username}] Failed to send commit {commit_hash}: {e}")
        elif msg["type"] == "commit":
            self.receive_commit(msg)

    def get_missing_commits(self, frontier):
        missing = []
        local = self.get_frontier_local()
        for user, remote_count in frontier.items():
            local_count = local.get(user, 0)
            if remote_count > local_count:
                try:
                    commits = run(["git", "rev-list", "--reverse", f"{user}~{remote_count - local_count}..{user}"]).splitlines()
                    missing.extend(commits)
                except Exception as e:
                    print(f"[{self.username}] Failed to get missing commits from {user}: {e}")
        return missing

    def create_commit_packet(self, commit_hash):
        raw = run(["git", "cat-file", "-p", commit_hash])
        lines = raw.splitlines()
        tree = lines[0].split()[1]
        parents = [line.split()[1] for line in lines if line.startswith("parent")]
        author_line = [line for line in lines if line.startswith("author")][0]
        author_parts = author_line.split()
        author = author_parts[1]
        author_time = " ".join(author_parts[2:])
        msg_index = lines.index("") + 1
        message = "\n".join(lines[msg_index:])
        return {
            "type": "commit",
            "author": author,
            "author_time": author_time,
            "message": message,
            "parents": parents,
            "tree": tree
        }

    def receive_commit(self, payload):
        tree = payload["tree"]
        parents = payload["parents"]
        message = payload["message"]
        author = payload["author"]
        author_time = payload["author_time"]

        try:
            for parent in parents:
                run(["git", "cat-file", "-e", parent])
        except Exception:
            print(f"[{self.username}] Missing parent(s) for commit from {author}, deferring...")
            self.pending_commits.append(payload)
            return

        args = ["git", "commit-tree", tree] + sum([["-p", p] for p in parents], [])
        commit_hash = run(args, env={
            **os.environ,
            "GIT_AUTHOR_NAME": author,
            "GIT_AUTHOR_EMAIL": f"{author}@example.com",
            "GIT_AUTHOR_DATE": author_time,
            "GIT_COMMITTER_NAME": author,
            "GIT_COMMITTER_EMAIL": f"{author}@example.com",
            "GIT_COMMITTER_DATE": author_time
        }, input=message)
        print(f"[{self.username}] Applied commit from {author}: {message[:40]}")

        run(["git", "update-ref", f"refs/heads/{author}", commit_hash])

    def retry_pending_commits(self):
        while self.running:
            time.sleep(5)
            for payload in self.pending_commits[:]:
                try:
                    for parent in payload["parents"]:
                        run(["git", "cat-file", "-e", parent])
                    self.receive_commit(payload)
                    self.pending_commits.remove(payload)
                except Exception:
                    continue

    def post_message(self, msg):
        run(["git", "fetch", "--all"])
        refs = run(["git", "for-each-ref", "--format=%(refname)"]).splitlines()
        parents = []
        for ref in refs:
            if ref.startswith("refs/heads/"):
                commit = run(["git", "rev-parse", ref])
                parents.append(commit)

        empty_tree = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
        timestamp = str(int(time.time())) + " +0000"
        args = ["git", "commit-tree", empty_tree] + sum([["-p", p] for p in parents], [])
        new_commit = run(args, input=msg, env={
            **os.environ,
            "GIT_AUTHOR_NAME": self.username,
            "GIT_AUTHOR_EMAIL": f"{self.username}@example.com",
            "GIT_AUTHOR_DATE": timestamp,
            "GIT_COMMITTER_NAME": self.username,
            "GIT_COMMITTER_EMAIL": f"{self.username}@example.com",
            "GIT_COMMITTER_DATE": timestamp
        })
        run(["git", "update-ref", f"refs/heads/{self.username}", new_commit])
        print(f"Message sent: {msg}")

    def print_frontier(self):
        frontier = self.get_frontier_local()
        print("\nMessages from other Users:")
        for user, count in sorted(frontier.items()):
            print(f" {user}: {count}")
        print("Press Enter to send message.")

    def run(self):
        print(f"Git-based chat as '{self.username}' started.")
        print("Type messages and press ENTER to send.")
        try:
            while self.running:
                msg = input()
                if msg.strip():
                    self.post_message(msg)
        except KeyboardInterrupt:
            self.running = False
            print("\nExiting...")
            if self.temp:
                print("Cleaning up temporary repo...")
                self.temp_dir.cleanup()

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python task3.py <username> <--temp>")
        sys.exit(1)

    username = sys.argv[1]
    if len(username) > 16:
        print("Username too long (max 16 characters)")
        sys.exit(1)

    temp = sys.argv[2] == "--temp"
    app = GitbasedChat(username, temp)
    app.run()
