"""Paper's native AppKit menu bar, always hosted on the main thread."""

import logging
import webbrowser

import AppKit
import Foundation
import objc


class PaperDelegate(Foundation.NSObject):
    @objc.python_method
    def configure(self, controller, url):
        self.controller = controller
        self.url = url
        self.status_item = AppKit.NSStatusBar.systemStatusBar().statusItemWithLength_(
            AppKit.NSVariableStatusItemLength
        )
        button = self.status_item.button()
        icon = AppKit.NSImage.imageWithSystemSymbolName_accessibilityDescription_(
            "square.and.pencil", "Paper"
        )
        if icon is not None:
            icon.setTemplate_(True)
            button.setImage_(icon)
        else:
            button.setTitle_("✎")
        self.menu = AppKit.NSMenu.alloc().initWithTitle_("Paper")
        self.menu.setAutoenablesItems_(False)
        self.menu.setDelegate_(self)
        self.add_item("Paper", None)
        self.status_label = self.add_item("Ready", None)
        self.add_item(url, "openEditor:")
        self.add_item("Open Editor & Controls…", "openEditor:")
        self.add_item("Copy Localhost Link", "copyLink:")
        self.menu.addItem_(AppKit.NSMenuItem.separatorItem())
        self.start_item = self.add_item("Start", "start:")
        self.pause_item = self.add_item("Pause", "pause:")
        self.stop_item = self.add_item("Stop", "stop:")
        self.menu.addItem_(AppKit.NSMenuItem.separatorItem())
        self.add_item("Accessibility Settings…", "permissions:")
        self.add_item("Input Monitoring Settings…", "inputPermissions:")
        self.add_item("Quit Paper", "quit:")
        self.status_item.setMenu_(self.menu)
        self.timer = Foundation.NSTimer.timerWithTimeInterval_target_selector_userInfo_repeats_(
            0.25, self, "tick:", None, True
        )
        Foundation.NSRunLoop.mainRunLoop().addTimer_forMode_(
            self.timer, Foundation.NSRunLoopCommonModes
        )
        self.tick_(None)

    @objc.python_method
    def add_item(self, title, action):
        item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, "")
        if action:
            item.setTarget_(self)
        item.setEnabled_(bool(action))
        self.menu.addItem_(item)
        return item

    @objc.python_method
    def perform(self, callback):
        try:
            callback()
        except Exception as exc:
            logging.getLogger(__name__).exception("Menu action failed")
            alert = AppKit.NSAlert.alloc().init()
            alert.setMessageText_("Paper")
            alert.setInformativeText_(str(exc))
            alert.runModal()
        self.tick_(None)

    def menuWillOpen_(self, menu):
        self.tick_(None)

    def tick_(self, timer):
        if self.controller.shutdown_event.is_set():
            self.stop_loop()
            return
        state = self.controller.state()
        label = state["status"] + (" · Preview" if state["dry_run"] else "")
        self.status_label.setTitle_(label)
        self.status_item.button().setToolTip_(f"Paper — {label}\n{self.url}")
        self.start_item.setEnabled_(not state["active"])
        self.pause_item.setTitle_("Resume" if state["paused"] else "Pause")
        self.pause_item.setEnabled_(state["active"] and not state["stopping"])
        self.stop_item.setEnabled_(state["active"] and not state["stopping"])

    def openEditor_(self, sender):
        webbrowser.open(self.url)

    def copyLink_(self, sender):
        pasteboard = AppKit.NSPasteboard.generalPasteboard()
        pasteboard.clearContents()
        pasteboard.setString_forType_(self.url, AppKit.NSPasteboardTypeString)

    def start_(self, sender):
        self.perform(self.controller.start)

    def pause_(self, sender):
        self.perform(self.controller.pause_or_resume)

    def stop_(self, sender):
        self.perform(self.controller.stop)

    def permissions_(self, sender):
        webbrowser.open("x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility")

    def inputPermissions_(self, sender):
        webbrowser.open("x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent")

    def quit_(self, sender):
        self.controller.request_shutdown()
        self.stop_loop()

    @objc.python_method
    def stop_loop(self):
        # Return from run() so Python can close the server and release keys.
        # stop: alone may leave AppKit waiting for the next UI event.
        app = AppKit.NSApplication.sharedApplication()
        app.stop_(None)
        event = AppKit.NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_(
            AppKit.NSApplicationDefined, (0, 0), 0, 0, 0, None, 0, 0, 0
        )
        app.postEvent_atStart_(event, True)

    def applicationShouldTerminate_(self, app):
        self.controller.request_shutdown()
        self.stop_loop()
        return AppKit.NSTerminateCancel

    def applicationShouldHandleReopen_hasVisibleWindows_(self, app, visible):
        self.openEditor_(None)
        return True


def run_tray(controller, url):
    application = AppKit.NSApplication.sharedApplication()
    application.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
    delegate = PaperDelegate.alloc().init()
    delegate.configure(controller, url)
    application.setDelegate_(delegate)
    try:
        application.run()
    finally:
        delegate.timer.invalidate()
        AppKit.NSStatusBar.systemStatusBar().removeStatusItem_(delegate.status_item)
        application.setDelegate_(None)
