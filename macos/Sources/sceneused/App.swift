import AppKit
import Foundation

final class AppDelegate: NSObject, NSApplicationDelegate {
    private var server: UnixServer?

    func applicationDidFinishLaunching(_ notification: Notification) {
        PermissionProbe.promptIfNeeded()
        let path = ProcessInfo.processInfo.environment["SCENEUSE_SOCK"] ?? "/tmp/sceneuse.sock"
        let server = UnixServer(path: path)
        do {
            try server.start()
            self.server = server
            fputs("sceneused \(sceneuseVersion) listening on \(path)\n", stderr)
        } catch {
            fputs("sceneused failed to bind \(path): \(error.localizedDescription)\n", stderr)
            exit(1)
        }
    }
}

@main
enum SceneusedMain {
    static func main() {
        let app = NSApplication.shared
        app.setActivationPolicy(.accessory)
        let delegate = AppDelegate()
        app.delegate = delegate
        withExtendedLifetime(delegate) {
            app.run()
        }
    }
}
