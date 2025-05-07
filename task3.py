import socket
import json
import threading
import time
import sys
import os
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

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

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
                "frontier": self.get_frontier_local()
            }
        #print(f"[{self.username}] Broadcasting frontier: {frontier}") MAYBE NOT NEEDED / WAS USED TO TEST IMPLEMENTATION
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
            #print(f"[{self.username}] Received frontier from {msg['from']}: {msg['frontier']}") MAYBE NOT NEEDED / WAS USED TO TEST IMPLEMENTATION
            missing = self.get_missing_commits(msg["frontier"])
            for commit_hash in missing:
                packet = self.create_commit_packet(commit_hash)
                self.sock.sendto(json.dumps(packet).encode(), addr)
        
        elif msg["type"] == "commit":
            self.receive_commit(msg)


    def get_missing_commits(self, frontier):
        local = self.get_frontier_local()
        missing = []
        for user, count in frontier.items():
            new_count = local.get(user, 0)
            if new_count > count:
                try:
                    rng = f"{user}~{new_count - count}..{user}"
                    commits = run(["git", "rev-list", "--reverse", rng]).splitlines()
                    missing.extend(commits)
                except:
                    continue
        return missing

    def create_commit_packet(self, commit_hash):
        raw = run(["git", "cat-file", "-p", commit_hash])
        lines = raw.splitlines()
        tree = lines[0].split()[1]
        parents = [line.split()[1] for line in lines if line.startswith("parent")]
        author_line = [line for line in lines if line.startswith("author")][0]
        author = author_line.split()[1]
        msg_index = lines.index("") + 1
        message = "\n".join(lines[msg_index:])
        return {
            "type": "commit",
            "author": author,
            "message": message,
            "parents": parents,
            "tree": tree }
        #(base) MacBook-Pro-5:DPI3 Lenny$ git cat-file -p b9a08620776980224b8dbee65970491f5b91a72e
        #tree 48b9a873ad6f9b22ae22cd1e0a3232debfdfa49c
        #parent e3cce7fe879b2fa33eb31cd653bb18298d11fed6
        #author Lennsco <leandro09.lika@gmail.com> 1746457445 +0200
        #committer Lennsco <leandro09.lika@gmail.com> 1746457445 +0200
        #Bugfix Macos broadcast


    def receive_commit(self, payload):
        tree = payload["tree"]
        parents = payload["parents"]
        message = payload["message"]
        author = payload["author"]

        args = ["git", "commit-tree", tree] + sum([["-p", p] for p in parents], [])
        commit_hash = run(args, env={
            **os.environ,
            "GIT_AUTHOR_NAME": author,
            "GIT_AUTHOR_EMAIL": f"{author}@example.com",
            "GIT_COMMITTER_NAME": author,
            "GIT_COMMITTER_EMAIL": f"{author}@example.com"
        }, input=message)
        run(["git", "update-ref", f"refs/heads/{author}", commit_hash])

    def post_message(self, msg):
        run(["git", "fetch", "--all"])
        branch = run(["git", "symbolic-ref", "--short", "HEAD"])
        #parents = run(["git", "rev-list", "--parents", "-n", "1", branch]).split()[1:]
        refs = run(["git", "for-each-ref", "--format=%(refname)"]).splitlines()
        parents = []
        for ref in refs:
            if ref.startswith("refs/heads/"):
                commit = run(["git", "rev-parse", ref])
                parents.append(commit)

        empty_tree  = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
        args = ["git", "commit-tree", empty_tree] + sum([["-p", p] for p in parents], [])
        new_commit = run(args, input=msg, env={
            **os.environ,
            "GIT_AUTHOR_NAME": self.username,
            "GIT_AUTHOR_EMAIL": f"{self.username}@example.com",
            "GIT_COMMITTER_NAME": self.username,
            "GIT_COMMITTER_EMAIL": f"{self.username}@example.com"
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

