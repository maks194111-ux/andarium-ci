// SPDX-License-Identifier: MIT
// Drives the running Andarium app with real touches for a fixed time: opens the
// language list of Android's setup screen and flings it up and down, with
// short pauses, so the harness can read frame rate, CPU and memory under load
// and see whether the app survives.
import XCTest

final class SoakTests: XCTestCase {
    private func log(_ text: String) {
        print("SOAK \(Int(Date().timeIntervalSince1970)) \(text)")
    }

    func testFlingForAWhile() throws {
        let environment = ProcessInfo.processInfo.environment
        let bundle = environment["ANDARIUM_BUNDLE"] ?? "local.andarium.ios18.a13"
        let seconds = Double(environment["SOAK_SECONDS"] ?? "") ?? 900
        executionTimeAllowance = seconds + 300

        let app = XCUIApplication(bundleIdentifier: bundle)
        app.activate()
        XCTAssertEqual(app.state, .runningForeground, "Andarium is not in the foreground")
        let pad = UIDevice.current.userInterfaceIdiom == .pad
        func point(_ x: Double, _ y: Double) -> XCUICoordinate {
            app.coordinate(withNormalizedOffset: CGVector(dx: x, dy: y))
        }

        // The app's own alerts would cover the guest's screen (in the Simulator
        // the keychain refuses the adb key, which raises the rotation alert).
        func dismissAlerts() {
            let button = app.alerts.buttons.firstMatch
            if button.exists {
                log("alert dismissed: \(app.alerts.firstMatch.label)")
                button.tap()
                Thread.sleep(forTimeInterval: 1)
            }
        }

        log("idle baseline begin")
        Thread.sleep(forTimeInterval: 30)
        log("idle baseline end")
        dismissAlerts()

        // "English (United States)" on the first setup screen opens a long list.
        point(0.4, pad ? 0.79 : 0.675).tap()
        Thread.sleep(forTimeInterval: 6)
        log("list opened")

        let began = Date()
        var flings = 0
        while Date().timeIntervalSince(began) < seconds {
            if app.state != .runningForeground {
                log("Andarium left the foreground: state \(app.state.rawValue)")
                XCTFail("Andarium left the foreground")
                return
            }
            let upward = (flings / 6) % 2 == 0
            let from = point(0.5, upward ? 0.85 : 0.45)
            let to = point(0.5, upward ? 0.45 : 0.85)
            from.press(forDuration: 0.03, thenDragTo: to, withVelocity: .fast, thenHoldForDuration: 0)
            flings += 1
            if flings % 6 == 0 {
                log("flings \(flings)")
                dismissAlerts()
                Thread.sleep(forTimeInterval: 2)
            } else {
                Thread.sleep(forTimeInterval: 0.4)
            }
        }
        log("done flings \(flings)")
        XCTAssertEqual(app.state, .runningForeground)
    }
}
