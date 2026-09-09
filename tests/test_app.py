import http.client
import json
from pathlib import Path
import tempfile
from threading import Event, Thread
from time import monotonic, sleep
import unittest
from unittest.mock import patch

import main
from storage import AppStorage, InstanceLock


def wait_until(predicate, timeout=2):
    end = monotonic() + timeout
    while not predicate():
        if monotonic() >= end:
            raise AssertionError("Timed out waiting for worker")
        sleep(.01)


class PaperTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.storage = AppStorage(Path(self.temp.name))
        self.controller = main.WebAutomationApp(main.ActivityConfig(dry_run=True), self.storage)

    def tearDown(self):
        self.controller.request_shutdown()
        wait_until(lambda: not self.controller.state()["active"])
        self.temp.cleanup()

    def test_start_pause_resume_stop_restart(self):
        with patch.object(main.keyboard, "Listener") as listener:
            self.controller.start()
            self.assertTrue(self.controller.state()["active"])
            self.controller.pause_or_resume()
            self.assertEqual(self.controller.state()["status"], "Paused")
            self.controller.pause_or_resume()
            self.assertEqual(self.controller.state()["status"], "Running")
            self.controller.stop()
            wait_until(lambda: not self.controller.state()["active"])
            self.controller.start()
            self.assertEqual(self.controller.state()["status"], "Running")
            listener.assert_not_called()

    def test_permission_error_is_visible(self):
        self.controller.settings.update(dry_run=False)
        with patch.object(main.AS, "AXIsProcessTrusted", return_value=False):
            with self.assertRaisesRegex(ValueError, "Accessibility"):
                self.controller.start()
        self.assertIn("Accessibility", self.controller.state()["error"])
        self.assertFalse(self.controller.state()["active"])

    def test_worker_failure_is_visible_and_can_restart(self):
        with patch.object(main.ActivitySimulator, "run", side_effect=RuntimeError("test error")):
            self.controller.start()
            wait_until(lambda: not self.controller.state()["active"])
        self.assertEqual(self.controller.state()["error"], "test error")
        self.controller.start()
        self.assertEqual(self.controller.state()["error"], "")

    def test_settings_are_validated_and_persisted(self):
        self.controller.update_settings({"intensity": "low", "tabs": True})
        saved = self.storage.read_config()
        self.assertEqual(saved["intensity"], "low")
        self.assertTrue(saved["enable_keyboard_tabbing"])
        self.assertNotIn("dry_run", saved)
        for invalid in ({"intensity": []}, {"mouse": "false"}, {"intensity": "bad"}):
            with self.assertRaises(ValueError):
                self.controller.update_settings(invalid)
        self.assertEqual(self.controller.state()["config"]["intensity"], "low")

    def test_failed_save_does_not_change_running_settings(self):
        with patch.object(self.storage, "save_config", side_effect=OSError("Disk full")):
            with self.assertRaises(OSError):
                self.controller.update_settings({"intensity": "high"})
        self.assertEqual(self.controller.state()["config"]["intensity"], "medium")

    def test_single_instance_and_note_survive_restart(self):
        first, second = InstanceLock(self.storage), InstanceLock(self.storage)
        try:
            self.assertTrue(first.acquire())
            first.publish("http://127.0.0.1:8765/")
            self.assertFalse(second.acquire())
            self.assertEqual(second.url(), "http://127.0.0.1:8765/")
            first.close()
            self.assertTrue(second.acquire())
        finally:
            first.close()
            second.close()
        self.storage.save_note("Hello 🌱\nA note.")
        self.assertEqual(AppStorage(self.storage.root).read_note(), "Hello 🌱\nA note.")

    def test_mouse_movement_can_be_stopped_midway(self):
        running, stopped = Event(), Event()
        running.set()
        simulator = main.ActivitySimulator(main.RuntimeSettings(main.ActivityConfig()), running, stopped)
        def move(*args, **kwargs):
            stopped.set()
        with patch.object(main.pyautogui, "size", return_value=(1440, 900)), \
             patch.object(main.pyautogui, "position", return_value=(500, 500)), \
             patch.object(main.pyautogui, "moveTo", side_effect=move) as move_to:
            before = monotonic()
            simulator.random_move()
            self.assertLess(monotonic() - before, .2)
            move_to.assert_called_once()

    def test_command_key_released_after_stop(self):
        running, stopped = Event(), Event()
        running.set()
        simulator = main.ActivitySimulator(main.RuntimeSettings(main.ActivityConfig()), running, stopped)
        with patch.object(main.pyautogui, "keyDown"), \
             patch.object(main.pyautogui, "press", side_effect=lambda _: stopped.set()), \
             patch.object(main.pyautogui, "keyUp") as key_up:
            simulator.switch_window()
            key_up.assert_called_once_with("command")

    def test_http_controls_notes_and_security(self):
        server = main.create_server(self.controller, 0)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def request(method, path, data=None, headers=None):
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
            body = json.dumps(data) if data is not None else None
            default_headers = {"Content-Type": "application/json", "X-Paper-Token": server.token}
            default_headers.update(headers or {})
            try:
                connection.request(method, path, body, default_headers)
                response = connection.getresponse()
                return response.status, response.read().decode()
            finally:
                connection.close()
        try:
            status, html = request("GET", "/")
            self.assertEqual(status, 200)
            self.assertIn(server.token, html)
            self.assertNotIn("__PAPER_TOKEN__", html)
            self.assertEqual(request("POST", "/api/start", {})[0], 200)
            self.assertEqual(request("POST", "/api/pause", {})[0], 200)
            self.assertEqual(request("POST", "/api/stop", {})[0], 200)
            self.assertEqual(request("POST", "/api/note", {"text": "Hello"})[0], 200)
            self.assertEqual(json.loads(request("GET", "/api/note")[1])["text"], "Hello")
            self.assertEqual(request("POST", "/api/start", {}, {"X-Paper-Token": "bad"})[0], 403)
            self.assertEqual(request("POST", "/api/start", {}, {"Origin": "https://example.com"})[0], 403)
            self.assertEqual(request("GET", "/", headers={"Host": "evil.example"})[0], 403)
            self.assertEqual(request("POST", "/api/settings", {"intensity": []})[0], 400)
            self.assertEqual(request("POST", "/api/quit", {})[0], 200)
            self.assertTrue(self.controller.shutdown_event.is_set())
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_busy_port_falls_back(self):
        first = main.create_server(self.controller, 0)
        second = main.create_server(self.controller, first.server_port)
        try:
            self.assertNotEqual(first.server_port, second.server_port)
            self.assertEqual(second.server_address[0], "127.0.0.1")
        finally:
            first.server_close()
            second.server_close()


if __name__ == "__main__":
    unittest.main()
