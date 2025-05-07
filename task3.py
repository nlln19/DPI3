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
        self.frontier_path = os.path.join(FRONTIER_DIR, self.username)
        os.makedirs(self.frontier_path, exist_ok=True)
        self.frontier_cache = self.load_frontier_disk()
        self.temp = temp
        self.running = True
        self.lock = threading.Lock()
        self.pending_commits = []  # Queue for out-of-order commits

        if self.temp:
            self.temp_dir = tempfile.TemporaryDirectory()
            os.chdir(self.temp_dir.name) #chdir changes the current working directory of the calling process to the directory specified in path
            run(["git", "init", "-b", self.username])
            run(["git", "config", "user.name", self.username])
            run(["git", "config", "user.email", f"{self.username}@example.com"])
            empty_tree = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
            init_commit = run(["git", "commit-tree", empty_tree], input=f"{self.username} joined (temp mode)")
            run(["git", "update-ref", f"refs/heads/{self.username}", init_commit])
            run(["git", "symbolic-ref", "HEAD", f"refs/heads/{self.username}"])
        else:
            if not os.path.exists(".git"):
                print("Error: Not inside a Git repository.")
                sys.exit(1)

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        #self.sock.sendto(b'test', (('255.255.255.255', 6969)))

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
            self.save_frontier_to_disk(frontier)  
            self.frontier_cache = frontier
            msg = {
                "type": "frontier",
                "from": self.username,
                "frontier": frontier
            }
        print(f"[{self.username}] Broadcasting frontier: {frontier}")  # DEBUG
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
                if user in ["main", "master", "HEAD"]:
                    continue
                if user not in frontier:
                    count = run(["git", "rev-list", "--count", ref])
                    frontier[user] = int(count)
        return frontier
                
    def handle_message(self, msg, addr):
        if msg["type"] == "frontier":
            print(f"[{self.username}] Received frontier from {msg['from']}: {msg['frontier']}")
            missing = self.get_missing_commits(msg["frontier"])
            print(f"[{self.username}] Calculated missing commits: {missing}")
            for commit_hash in missing:
                print(f"[{self.username}] Sending commit {commit_hash} to {addr}")  # DEBUG
                acket = self.create_commit_packet(commit_hash)
                try:
                    self.sock.sendto(json.dumps(packet).encode(), addr)
                except Exception as e:
                    print(f"[{self.username}] Failed to send commit {commit_hash}: {e}")
        elif msg["type"] == "commit":
            print(f"[{self.username}] Received commit packet: {msg['message'][:40]} ({msg['author']})")  # DEBUG
            self.receive_commit(msg)


    def get_missing_commits(self, remote_frontier):
        """
        Determine which commits the peer is missing.
        """
        try:
            log_output = run([
                "git", "log", "--all", "--topo-order",
                "--pretty=format:%an;%H;%P;%s"
            ])
        except Exception as e:
            print(f"[{self.username}] Failed to get commit log: {e}")
            return []

        commit_lines = log_output.splitlines()
        gaps = {}
        for line in commit_lines:
            try:
                author, commit_hash, parents_str, _ = line.split(';', 3)
            except ValueError:
                continue

            peer_count = remote_frontier.get(author, 0)
            local_count = self.frontier_cache.get(author, 0)
            if author not in gaps:
                # If we have more commits for that author than they do, calculate the gap.
                if local_count > peer_count:
                    gaps[author] = {
                        "count": local_count - peer_count,
                        "commits": []
                    }

            if author in gaps and gaps[author]["count"] > 0:
                gaps[author]["commits"].append(commit_hash)
                gaps[author]["count"] -= 1

        # Flatten all missing commits from gaps
        all_missing = []
        for info in gaps.values():
            # Ensure commits are sent oldest-to-newest
            all_missing.extend(reversed(info["commits"]))
        return all_missing


    
    #(base) MacBook-Pro-5:Silvan Lenny$ git log --author=Silvan --reverse --pretty=format:%H
    #6961300e43a51412038e36511adbe765b0d2d229
    #7f4a0a2f1b9c103736449f2439153a14b66f6f1a
    #3f69f8593320603ff3fa35dcf894761f1df6a193
    #67efd2e8b6dad0625e203228f2a21fded3bdb217
    #485e687e1c57c397d9249129146f478e93ab8f35
    #cd1bf3a407254d6eccd88ed25212677997d01bac
    #4d5ac75c2d6df1c596cdb08fd6789cb1a9492eb3
    #be721c213686d1d26e7e0f196f486ccf44632865
    #90b387a53b2244773e2b626c441309decabd57ad
    #da8330a7a422ae7db8f11ee43cb0abe72001340b
    #97eb484df07236b08828a2997bea57bb49f40af9
    #fad017f31c9846a9a9e7e27a6072c68907d32c73
    #12bbf474363445d652d3bd6841b3bfbaa6a33fe4

    def create_commit_packet(self, commit_hash):
        print(f"[{self.username}] Creating packet for commit {commit_hash}")  # DEBUG
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
        print(f"[{self.username}] Created commit hash: {commit_hash}")

        run(["git", "update-ref", f"refs/heads/{author}", commit_hash])

        # Update and persist frontier
        self.frontier_cache = self.get_frontier_local()
        self.save_frontier_to_disk(self.frontier_cache)


    def retry_pending_commits(self):
        while self.running:
            time.sleep(5)
            for payload in self.pending_commits[:]:
                try:
                    for parent in payload["parents"]:
                        run(["git", "cat-file", "-e", parent])
                    self.receive_commit(payload)
                    self.pending_commits.remove(payload)
                except Exception as e:
                    print(f"[{self.username}] Still missing parents for retry: {payload['message'][:30]} - {e}")


    def post_message(self, msg):
        print(f"[{self.username}] Creating new commit with message: {msg}")  # DEBUG
        run(["git", "fetch", "--all"])
        refs = run(["git", "for-each-ref", "--format=%(refname)"]).splitlines()
        parents = []
        for ref in refs:
            if ref.startswith("refs/heads/"):
                commit = run(["git", "rev-parse", ref])
                parents.append(commit)

        empty_tree = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
        timestamp = "1715058000 +0000"
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
        print(f"[{self.username}] Commit hash: {new_commit}")  #DEBUG
        print(f"Message sent: {msg}")
    
    def load_frontier_disk(self):
        frontier = {}
        if not os.path.exists(self.frontier_path):
            return frontier
        for fname in os.listdir(self.frontier_path):
            fpath = os.path.join(self.frontier_path, fname)
            try:
                with open(fpath, "r") as f:
                    count = int(f.read().strip())
                    frontier[fname] = count
            except Exception:
                continue
        return frontier

    def save_frontier_to_disk(self, frontier):
        for user, count in frontier.items():
            fpath = os.path.join(self.frontier_path, user)
            try:
                with open(fpath, "w") as f:
                    f.write(str(count))
            except Exception as e:
                print(f"[{self.username}] Failed to write frontier for {user}: {e}")
    
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
