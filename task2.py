import socket
import json
import threading
import time
import sys
import os


BROADCAST_PORT = 6969
BROADCAST_INTERVAL = 10  # 10 sekunden
PACKET_SIZE_LIMIT = 576 
FRONTIER_DIR = "frontiers"

class FrontierChat:
    def __init__(self, username, temp):
        self.username = username
        ##self.state = {username: 0}  # eigene Nachrichtenzahl
        self.temp = temp
        self.lock = threading.Lock()
        self.running = True

        
        self.state = self.load_state() if not temp else {username: 0}
        if self.username not in self.state:
            self.state[self.username] = 0

        # UDP Socket für Broadcast
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except Exception:
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1) # Broadcast erlauben
        self.sock.bind(('', BROADCAST_PORT)) # mit Broadcastport verbinden


        # Empfangen starten
        threading.Thread(target=self.listen, daemon=True).start()

        # Broadcast starten (alle 10s wirds aktualisiert)
        threading.Thread(target=self.broadcast_loop, daemon=True).start()

    def listen(self):
        while self.running:
            try:
                data, _ = self.sock.recvfrom(PACKET_SIZE_LIMIT)
                message = json.loads(data.decode('utf-8'))
                self.merge(message)
            except Exception as e:
                print("Error receiving packet:", e)

    def merge(self, incoming_state):
        with self.lock:
            changed = False
            for user, count in incoming_state.items():
                if user not in self.state or self.state[user] < count:
                    self.state[user] = count
                    changed = True
            if changed:
                self.save_state()
                self.print_state()

    def broadcast_loop(self):
        while self.running:
            time.sleep(BROADCAST_INTERVAL)
            self.broadcast()

    def broadcast(self):
        with self.lock:
            message = json.dumps(self.state)
        self.sock.sendto(message.encode('utf-8'), ('<broadcast>', BROADCAST_PORT))

    def increment_own_count(self):
        with self.lock:
            self.state[self.username] += 1
            self.save_state()
            self.print_state()

    def print_state(self):
        print("\nMessages sent:")
        for user, count in sorted(self.state.items()):
            print(f"  {user}: {count}")
        print("Press 'ENTER' to send message...")

    def load_state(self):
        path = os.path.join(FRONTIER_DIR, self.username)
        state = {}
        if os.path.isdir(path):
            for filename in os.listdir(path):
                try:
                    peer = filename.replace(".txt", "")
                    with open(os.path.join(path, filename), "r") as f:
                     count = int(f.read().strip())
                     state[peer] = count
                except Exception as e:
                    print(f"Unable to load state for file {filename}: {e}" )
        return state

        

    def save_state(self):
        if self.temp:
            return
        path = os.path.join(FRONTIER_DIR, self.username)
        os.makedirs(path, exist_ok=True)
        for peer, count in self.state.items():
            try:
                with open(os.path.join(path, f"{peer}.txt"), 'w') as f:
                    f.write(str(count))
            except Exception as e:
             print(f"Unable to save the state for {peer}...: {e}")
       

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
    if len(sys.argv) != 3:
        print("Usage: python task01.py <username> <--temp>")
        print("If you want to store frontiers replace --temp with store")
        sys.exit(1)

    username = sys.argv[1]
    if len(username) > 16:
        print("Username too long (max 16 characters)")
        sys.exit(1)

    temp = sys.argv[2] == "--temp"
    
    

    app = FrontierChat(username, temp)
    app.run()