"""The relay that gives the app container its only two routes (threat model gap 6). Local sockets only."""

import asyncio
import socket
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # project root

import port_relay as pr  # noqa: E402


class Rules(unittest.TestCase):
    def test_valid_routes(self):
        self.assertEqual(pr.parse_rules(["8501=localai:8501", "11434=host.docker.internal:11434"]),
                         [(8501, "localai", 8501), (11434, "host.docker.internal", 11434)])

    def test_bad_routes_are_refused(self):
        for bad in (["8501"], ["8501=localai"], ["x=localai:1"], ["70000=a:1"], ["1=a:0"], ["1=a b:2"],
                    ["1=a;rm:2"], ["1=a:1", "1=b:2"], []):
            with self.subTest(bad=bad), self.assertRaises(pr.RuleError):
                pr.parse_rules(bad)

    def test_main_refuses_bad_routes_without_listening(self):
        self.assertEqual(pr.main(["nonsense"]), 2)


class Forwarding(unittest.TestCase):
    """A real relay in a thread, forwarding to a real echo server on 127.0.0.1."""

    def setUp(self):
        self.echo = socket.socket()
        self.echo.bind(("127.0.0.1", 0))
        self.echo.listen()
        self.echo_port = self.echo.getsockname()[1]
        threading.Thread(target=self._echo_forever, daemon=True).start()
        self.relays = []
        self.relay_port = self._start_relay(self.echo_port)

    def tearDown(self):
        for loop, task, thread in self.relays:
            loop.call_soon_threadsafe(task.cancel)
            thread.join(timeout=5)
        self.echo.close()

    def _echo_forever(self):
        while True:
            try:
                conn, _ = self.echo.accept()
            except OSError:
                return
            threading.Thread(target=self._echo_one, args=(conn,), daemon=True).start()

    @staticmethod
    def _echo_one(conn):
        with conn:
            while data := conn.recv(65536):
                conn.sendall(data)

    def _start_relay(self, target_port):
        ready = threading.Event()
        bound, handles = [], []

        def run():
            loop = asyncio.new_event_loop()
            task = loop.create_task(pr.serve([(0, "127.0.0.1", target_port)], bind="127.0.0.1",
                                             ready=lambda ports: (bound.extend(ports), ready.set())))
            handles.extend([loop, task])
            try:
                loop.run_until_complete(task)
            except asyncio.CancelledError:
                pass
            finally:
                loop.close()

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        self.assertTrue(ready.wait(5), "relay did not start")
        self.relays.append((handles[0], handles[1], thread))
        return bound[0][1]

    def _roundtrip(self, payload, port=None):
        with socket.create_connection(("127.0.0.1", port or self.relay_port), timeout=5) as s:
            s.sendall(payload)
            got = b""
            while len(got) < len(payload):
                part = s.recv(65536)
                if not part:
                    break
                got += part
            return got

    def test_bytes_come_back_unchanged(self):
        self.assertEqual(self._roundtrip(b"GET / HTTP/1.1\r\nHost: x\r\n\r\n"), b"GET / HTTP/1.1\r\nHost: x\r\n\r\n")

    def test_large_payload(self):
        payload = bytes(range(256)) * 4096  # 1 MiB
        self.assertEqual(self._roundtrip(payload), payload)

    def test_several_connections_at_once(self):
        results = [None] * 8

        def one(i):
            results[i] = self._roundtrip(f"conn {i}".encode() * 100)

        threads = [threading.Thread(target=one, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)
        self.assertEqual(results, [f"conn {i}".encode() * 100 for i in range(8)])

    def test_a_dead_upstream_closes_the_connection(self):
        from unittest import mock
        dead = socket.socket()
        dead.bind(("127.0.0.1", 0))  # bound but not listening: refused, or (in some sandboxes) never answered
        port = self._start_relay(dead.getsockname()[1])
        try:
            with mock.patch.object(pr, "CONNECT_TIMEOUT", 1), \
                    socket.create_connection(("127.0.0.1", port), timeout=5) as s:
                s.sendall(b"hello")
                self.assertEqual(s.recv(10), b"")
        finally:
            dead.close()


if __name__ == "__main__":
    unittest.main()
